from odoo import models, fields, api, _
from odoo.exceptions import UserError
import os

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    blockchain_rpc_url = fields.Char(
        string='Blockchain RPC URL',
        config_parameter='odoo_blockchain_core.rpc_url',
        help="E.g: https://sepolia.infura.io/v3/YOUR-PROJECT-ID"
    )
    blockchain_contract_address = fields.Char(
        string='Contract Address',
        config_parameter='odoo_blockchain_core.contract_address',
        help="Address of the UniversalDocumentRegistry contract."
    )
    blockchain_chain_id = fields.Integer(
        string='Chain ID',
        config_parameter='odoo_blockchain_core.chain_id',
        default=11155111, # Sepolia default
        help="Chain ID for transaction signing (prevents replay attacks)."
    )
    blockchain_max_gas_price_gwei = fields.Float(
        string='Max Gas Price (Gwei)',
        config_parameter='odoo_blockchain_core.max_gas_price_gwei',
        default=50.0,
        help="Maximum gas price (in Gwei) allowed for transactions. If network is more expensive, transactions will wait in queue."
    )
    
    blockchain_private_key_status = fields.Selection(
        [('set', 'Configured'), ('missing', 'Missing')],
        string='Private Key Status',
        compute='_compute_key_status'
    )

    @api.depends('blockchain_rpc_url') # Dependencia ficticia para activar el recálculo o la carga cuando se cambia la configuración
    def _compute_key_status(self):
        key = os.environ.get('ODOO_BLOCKCHAIN_PRIVATE_KEY')
        for record in self:
            record.blockchain_private_key_status = 'set' if key else 'missing'
    
    def action_check_blockchain_connection(self):
        """ Test connection to RPC and check Balance """
        self.ensure_one()
        try:
            from web3 import Web3
        except ImportError:
            raise UserError(_("Web3 library not installed."))

        rpc = self.blockchain_rpc_url
        if not rpc:
            raise UserError(_("Please configure RPC URL first."))

        w3 = Web3(Web3.HTTPProvider(rpc))
        if not w3.is_connected():
            raise UserError(_("Could not connect to RPC URL."))

        # Comprobamos la clave privada y balance
        key = os.environ.get('ODOO_BLOCKCHAIN_PRIVATE_KEY')
        if not key:
            raise UserError(_("Connection Successful, but Private Key ENV VAR is missing."))
        
        try:
            account = w3.eth.account.from_key(key)
            balance = w3.eth.get_balance(account.address)
            balance_eth = w3.from_wei(balance, 'ether')
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connection Successful"),
                    'message': _("Connected to Chain ID %s.\nWallet: %s\nBalance: %s ETH") % (w3.eth.chain_id, account.address, balance_eth),
                    'type': 'success',
                }
            }
        except Exception as e:
             raise UserError(_("Private Key Error: %s") % str(e))
