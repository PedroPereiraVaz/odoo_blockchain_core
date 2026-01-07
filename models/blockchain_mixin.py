from odoo import models, fields, api, _
from odoo.exceptions import UserError
import hashlib

class BlockchainCertifiedMixin(models.AbstractModel):
    _name = 'blockchain.certified.mixin'
    _description = 'Mixin to enable Blockchain Universal Registration'

    blockchain_entry_id = fields.Many2one('blockchain.registry.entry', string='Blockchain Entry', copy=False, readonly=True)
    blockchain_status = fields.Selection(related='blockchain_entry_id.status', store=True, readonly=True)
    blockchain_hash = fields.Char(related='blockchain_entry_id.content_hash', readonly=True)
    
    def _compute_blockchain_hash(self):
        """ Abstract Method: Must return the SHA256 hex string of the content to certify. """
        raise NotImplementedError("Models consuming blockchain.certified.mixin must implement _compute_blockchain_hash()")

    def _post_blockchain_message(self, body, subtype_xmlid='mail.mt_note'):
        """ Allow the registry to post back to this record's chatter """
        self.ensure_one()
        if hasattr(self, 'message_post'):
            self.message_post(body=body, subtype_xmlid=subtype_xmlid)
        
    def action_blockchain_register(self):
        """
        Public action to trigger registration.
        It creates the queue entry.
        """
        for record in self:
            content_hash = record._compute_blockchain_hash()
            if not content_hash:
                raise UserError(_("Could not compute hash for this record."))

            # 1. Check if already exists
            entry = self.env['blockchain.registry.entry'].search([
                ('content_hash', '=', content_hash)
            ], limit=1)

            if not entry:
                # 2. Create new
                entry = self.env['blockchain.registry.entry'].create({
                    'content_hash': content_hash,
                    'related_model': record._name,
                    'related_id': record.id,
                    'status': 'pending'
                })
                record._post_blockchain_message(_("Blockchain Registration Requested. Hash: %s") % content_hash)
            else:
                # Link existing
                if entry.related_model != record._name or entry.related_id != record.id:
                     # Warn: This hash exists for another object? 
                     # For now, just link it if we add a Many2one to the mixin later.
                     pass
                
                # If it was error, retry
                if entry.status == 'error':
                    entry.status = 'pending'
                    record._post_blockchain_message(_("Retrying Blockchain Registration."))

            record.blockchain_entry_id = entry
            
    def action_blockchain_revoke(self):
        """
        Public action to trigger revocation.
        """
        for record in self:
            if not record.blockchain_entry_id:
                raise UserError(_("No blockchain entry found to revoke."))
            
            record.blockchain_entry_id.action_revoke()
            record._post_blockchain_message(_("Revocation Requested for Hash: %s") % record.blockchain_entry_id.content_hash)

    def action_blockchain_verify(self):
        """ Manual verification check """
        self.ensure_one()
        if self.blockchain_entry_id:
            return self.blockchain_entry_id.action_verify_on_chain_manual()
        raise UserError(_("No blockchain entry linked."))
