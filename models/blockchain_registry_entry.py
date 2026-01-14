import logging
import os
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .abi import UNIVERSAL_REGISTRY_ABI

_logger = logging.getLogger(__name__)

try:
    import warnings
    # Suprimimos websockets.legacy deprecation warning proveniente de la dependencia de web3
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.legacy is deprecated.*")
        from web3 import Web3
except ImportError as e:
    _logger.warning(f"Failed to import Web3: {e}")
    Web3 = None

class BlockchainRegistryEntry(models.Model):
    _name = 'blockchain.registry.entry'
    _description = 'Blockchain Document Registry Log'
    _order = 'create_date desc'
    _rec_name = 'content_hash'

    # --- Estados ---
    content_hash = fields.Char(string='Document Hash', required=True, index=True, copy=False, help="SHA256/Keccak256 hash of the document content.")
    
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending (Queue)'),
        ('submitted', 'Submitted (Waiting Conf)'),
        ('confirmed', 'Confirmed'),
        ('revocation_pending', 'Pending Revocation'),
        ('revocation_submitted', 'Revocation Submitted'),
        ('revoked', 'Revoked'),
        ('error', 'Error')
    ], string='Status', default='draft', required=True, copy=False, index=True)

    # --- Metadata ---
    tx_hash = fields.Char(string='Transaction Hash', copy=False, readonly=True)
    block_timestamp = fields.Datetime(string='Block Timestamp', copy=False, readonly=True)
    
    revocation_tx_hash = fields.Char(string='Revocation Tx Hash', copy=False, readonly=True)
    revocation_date = fields.Datetime(string='Revocation Date', copy=False, readonly=True)
    
    error_message = fields.Text(string='Error Message', copy=False, readonly=True)
    
    # --- Relacion ---
    related_model = fields.Char(string='Origin Model', index=True)
    related_id = fields.Integer(string='Origin ID', index=True)
    
    # --- Hash Unico ---
    _sql_constraints = [
        ('content_hash_unique', 'unique(content_hash)', 'This document hash has already been registered.')
    ]

    def _post_to_related_chatter(self, body, subtype_xmlid='mail.mt_note'):
        """ Helper para publicar mensajes en el chat del documento de origen """
        self.ensure_one()
        if self.related_model and self.related_id:
            try:
                record = self.env[self.related_model].browse(self.related_id)
                if record.exists() and hasattr(record, 'message_post'):
                    record.message_post(body=body, subtype_xmlid=subtype_xmlid)
            except Exception as e:
                _logger.warning(f"Could not post to related chatter: {e}")

    def action_register(self):
        """ Cambia el estado para que se ponga en cola para registro """
        for record in self:
            if record.status in ['draft', 'error']:
                record.status = 'pending'
                record._post_to_related_chatter(_("Blockchain Registration Queued (Status: Pending)"))

    def action_reset_draft(self):
        for record in self:
             if record.status == 'error':
                 record.status = 'draft'

    def action_revoke(self):
        """ Cambia el estado para que se ponga en cola para revocar """
        for record in self:
            if record.status != 'confirmed':
                raise UserError(_("You can only revoke a document that has been fully confirmed on the blockchain."))
            
            record.status = 'revocation_pending'
            record._post_to_related_chatter(_("Revocation Requested. Waiting for blockchain submission..."))

    @api.model
    def process_blockchain_queue(self):
        """ CRON: Toma las transacciones pendientes y revocaciones para enviarlas a la blockchain """
        if not Web3:
             _logger.warning("Web3 not installed, skipping queue.")
             return

        # 1. Config Check
        params = self.env['ir.config_parameter'].sudo()
        rpc = params.get_param('odoo_blockchain_core.rpc_url')
        contract_addr = params.get_param('odoo_blockchain_core.contract_address')
        chain_id = int(params.get_param('odoo_blockchain_core.chain_id', 1))
        max_gas_gwei = float(params.get_param('odoo_blockchain_core.max_gas_price_gwei', 50.0))
        private_key = os.environ.get('ODOO_BLOCKCHAIN_PRIVATE_KEY')

        if not all([rpc, contract_addr, private_key]):
            return # Falta configuración

        # 2. Conexión
        w3 = Web3(Web3.HTTPProvider(rpc))
        if not w3.is_connected():
            return
        
        # 3. Comprobamos el gas, si supera el umbral, dejamos en cola las transacciones
        current_gas_wei = w3.eth.gas_price
        current_gas_gwei = w3.from_wei(current_gas_wei, 'gwei')
        
        if current_gas_gwei > max_gas_gwei:
            _logger.info(f"Gas too high ({current_gas_gwei} > {max_gas_gwei}). Skipping queue.")
            return

        contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=UNIVERSAL_REGISTRY_ABI)
        account = w3.eth.account.from_key(private_key)

        # 3a. Procesamos los registros
        pending_records = self.search([('status', '=', 'pending')], limit=3)
        for record in pending_records:
            self._submit_transaction(w3, contract, account, record, is_revocation=False, chain_id=chain_id)

        # 3b. Procesamos las revocaciones
        pending_revocations = self.search([('status', '=', 'revocation_pending')], limit=3)
        for record in pending_revocations:
            self._submit_transaction(w3, contract, account, record, is_revocation=True, chain_id=chain_id)

    def _submit_transaction(self, w3, contract, account, record, is_revocation, chain_id):
        """ Helper para construir, firmar y enviar transacción """
        try:
            nonce = w3.eth.get_transaction_count(account.address, 'pending')
            
            # Construimos el hash
            try:
                hash_bytes = bytes.fromhex(record.content_hash)
            except:
                hash_bytes = record.content_hash.encode()

            if is_revocation:
                func = contract.functions.revokeDocument(hash_bytes)
                next_status = 'revocation_submitted'
                tx_field = 'revocation_tx_hash'
            else:
                func = contract.functions.registerDocument(hash_bytes)
                next_status = 'submitted'
                tx_field = 'tx_hash'

            # Construimos la transacción
            txn = func.build_transaction({
                'chainId': chain_id,
                'gasPrice': w3.eth.gas_price,
                'from': account.address,
                'nonce': nonce
            })
            
            # Firmamos la transaccion y la enviamos
            signed_txn = w3.eth.account.sign_transaction(txn, private_key=account.key)
            tx_hash_bytes = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_hash_hex = w3.to_hex(tx_hash_bytes)
            
            vals = {
                'status': next_status,
                'error_message': False,
                tx_field: tx_hash_hex
            }
            record.write(vals)
            
            action_label = "Revocación" if is_revocation else "Registro"
            msg = f"Transacción de {action_label} Enviada. Hash Tx: {tx_hash_hex}"
            record._post_to_related_chatter(msg)
            _logger.info(f"{action_label} Tx sent for {record.content_hash}: {tx_hash_hex}")
            
        except Exception as e:
            record.write({
                'status': 'error',
                'error_message': str(e)
            })
            _logger.exception(f"Failed to submit tx for {record.content_hash}")

    @api.model
    def check_transaction_receipts(self):
        """ CRON: Comprobamos las transacciones enviadas (registros y revocaciones) """
        if not Web3: return
        
        records_reg = self.search([('status', '=', 'submitted'), ('tx_hash', '!=', False)])
        records_rev = self.search([('status', '=', 'revocation_submitted'), ('revocation_tx_hash', '!=', False)])
        
        if not records_reg and not records_rev: return

        params = self.env['ir.config_parameter'].sudo()
        rpc = params.get_param('odoo_blockchain_core.rpc_url')
        w3 = Web3(Web3.HTTPProvider(rpc))
        
        for record in records_reg:
            self._check_single_receipt(w3, record, is_revocation=False)
            
        for record in records_rev:
             self._check_single_receipt(w3, record, is_revocation=True)

    def _check_single_receipt(self, w3, record, is_revocation):
        tx_hash = record.revocation_tx_hash if is_revocation else record.tx_hash
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt:
                if receipt['status'] == 1:
                    # Exitoso
                    if is_revocation:
                        record.status = 'revoked'
                        record.revocation_date = fields.Datetime.now()
                        xml_id = 'odoo_blockchain_core.email_template_blockchain_revoked'
                    else:
                        record.status = 'confirmed'
                        # Optional: Obtenemos el block timestamp
                        block = w3.eth.get_block(receipt['blockNumber'])
                        from datetime import datetime
                        record.block_timestamp = datetime.fromtimestamp(block['timestamp'])
                        xml_id = 'odoo_blockchain_core.email_template_blockchain_connected'
                    
                    # Render Template
                    try:
                        template = self.env.ref(xml_id, raise_if_not_found=False)
                        if template:
                            # Renderizamos el body_html pasando los IDs
                            msg = template._render_field('body_html', [record.id], compute_lang=True)[record.id]
                        else:
                            msg = "El estado del documento se ha actualizado en la Blockchain (Plantilla no encontrada)."
                    except Exception as e:
                        _logger.error(f"Error rendering template {xml_id}: {e}")
                        msg = "El estado del documento se ha actualizado en la Blockchain."
                    
                    record._post_to_related_chatter(msg, subtype_xmlid='mail.mt_comment')
                else:
                    # Error al registrar transacción
                    record.status = 'error'
                    record.error_message = f"Transacción {tx_hash} Revertida en la Cadena"
                    record._post_to_related_chatter("Acción FALLIDA en Blockchain (Revertida).", subtype_xmlid='mail.mt_comment')

        except Exception:
            # Tx no encontrada aún (pending in mempool)
            pass
    
    def action_verify_on_chain_manual(self):
        """ Función para verificar manualmente una transacción """
        self.ensure_one()
        if not Web3: raise UserError("Web3 missing")
        
        params = self.env['ir.config_parameter'].sudo()
        rpc = params.get_param('odoo_blockchain_core.rpc_url')
        contract_addr = params.get_param('odoo_blockchain_core.contract_address')
        
        w3 = Web3(Web3.HTTPProvider(rpc))
        contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=UNIVERSAL_REGISTRY_ABI)
        
        try:
             # Hash prep
             try:
                hash_bytes = bytes.fromhex(self.content_hash)
             except:
                hash_bytes = self.content_hash.encode()

             result = contract.functions.verifyDocument(hash_bytes).call()
             is_valid = result[0]
             
             msg = _("Chain Verification: %s") % ("VALID" if is_valid else "INVALID / REVOKED")
             if is_valid:
                 msg += f"\nIssuer: {result[1]} ({result[4]})"
                 if self.status != 'confirmed': 
                     self.status = 'confirmed' # Auto correción
             else:
                 if self.status == 'revoked':
                     msg = _("Correctly verified as REVOKED on chain.")
             
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Verification Result"),
                    'message': msg,
                    'type': 'success' if is_valid or self.status == 'revoked' else 'warning',
                    'sticky': True,
                }
            }
        except Exception as e:
            raise UserError(str(e)) 
