from odoo import http
from odoo.http import request

class BlockchainVerifierController(http.Controller):
    
    @http.route('/blockchain/verify', type='http', auth='public', website=True, sitemap=True)
    def verify_document_page(self, **kwargs):
        """ Renders the public verification page with backend config """
        
        # 1. Get Params from Config (Sudo)
        params = request.env['ir.config_parameter'].sudo()
        rpc_url = params.get_param('odoo_blockchain_core.rpc_url')
        contract_addr = params.get_param('odoo_blockchain_core.contract_address')
        
        values = {
            'rpc_url': rpc_url,
            'contract_address': contract_addr
        }
        
        return request.render('odoo_blockchain_core.verification_page_template', values)
