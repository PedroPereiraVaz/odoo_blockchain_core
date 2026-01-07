from odoo.tests import common
from odoo.exceptions import UserError
from unittest.mock import MagicMock, patch
import os
import json

class TestBlockchainCore(common.TransactionCase):

    def setUp(self):
        super(TestBlockchainCore, self).setUp()
        self.entry_model = self.env['blockchain.registry.entry']
        self.ConfigProp = self.env['ir.config_parameter'].sudo()
        
        # Setup Basic Config
        self.ConfigProp.set_param('odoo_blockchain_core.rpc_url', 'https://mock.rpc')
        self.ConfigProp.set_param('odoo_blockchain_core.contract_address', '0x1234567890123456789012345678901234567890')
        self.ConfigProp.set_param('odoo_blockchain_core.chain_id', '11155111')
        self.ConfigProp.set_param('odoo_blockchain_core.max_gas_price_gwei', '50.0')

        # Mock dummy record for Mixin testing
        # We create a temporary model instance (conceptually) or just simulate the mixin call
        # Since we can't create real dynamic models in standard tests easily without registry teardown,
        # we will test the Registry Entry directly or mock the mixin behavior.
        
    def test_01_registry_entry_lifecycle(self):
        """ Test entry creation and status flow """
        entry = self.entry_model.create({
            'content_hash': '0x' + 'a'*64,
            'related_model': 'res.partner',
            'related_id': 1
        })
        self.assertEqual(entry.status, 'draft')
        
        entry.action_register()
        self.assertEqual(entry.status, 'pending')

    @patch.dict(os.environ, {'ODOO_BLOCKCHAIN_PRIVATE_KEY': '0x' + 'b'*64})
    @patch('odoo.addons.odoo_blockchain_core.models.blockchain_registry_entry.Web3')
    def test_02_process_queue_success(self, MockWeb3):
        """ Test successful submission to chain """
        # Setup Mock Web3
        mock_w3 = MagicMock()
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider.return_value = MagicMock()
        mock_w3.is_connected.return_value = True
        
        # Gas Price Mock (20 Gwei < 50 Max)
        mock_w3.eth.gas_price = 20 * 10**9
        mock_w3.from_wei.side_effect = lambda val, unit: val / 10**9 if unit == 'gwei' else val
        
        # Account Mock
        mock_account = MagicMock()
        mock_account.address = '0xSender'
        mock_w3.eth.account.from_key.return_value = mock_account
        
        # Contract Mock
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract
        mock_contract.functions.registerDocument.return_value.build_transaction.return_value = {'data': '0x...'}
        
        # Create Pending Entry
        entry = self.entry_model.create({
            'content_hash': '0x' + 'c'*64,
            'status': 'pending'
        })
        
        # Run Cron Method
        self.entry_model.process_blockchain_queue()
        
        # Checks
        self.assertEqual(entry.status, 'submitted', "Status should change to submitted")
        self.assertTrue(entry.tx_hash, "Tx hash should be set")
        mock_w3.eth.send_raw_transaction.assert_called_once()
        
    @patch.dict(os.environ, {'ODOO_BLOCKCHAIN_PRIVATE_KEY': '0x' + 'b'*64})
    @patch('odoo.addons.odoo_blockchain_core.models.blockchain_registry_entry.Web3')
    def test_03_process_queue_high_gas(self, MockWeb3):
        """ Test gas protection """
        mock_w3 = MagicMock()
        MockWeb3.return_value = mock_w3
        mock_w3.is_connected.return_value = True
        
        # Gas Price Mock (100 Gwei > 50 Max)
        mock_w3.eth.gas_price = 100 * 10**9 
        mock_w3.from_wei.side_effect = lambda val, unit: val / 10**9 if unit == 'gwei' else val
        
        entry = self.entry_model.create({
            'content_hash': '0x' + 'd'*64,
            'status': 'pending'
        })
        
        self.entry_model.process_blockchain_queue()
        
        # Checks
        self.assertEqual(entry.status, 'pending', "Status should remain pending due to high gas")
        mock_w3.eth.send_raw_transaction.assert_not_called()

    @patch('odoo.addons.odoo_blockchain_core.models.blockchain_registry_entry.Web3')
    def test_04_check_receipts(self, MockWeb3):
        """ Test receipt confirmation """
        mock_w3 = MagicMock()
        MockWeb3.return_value = mock_w3
        
        entry = self.entry_model.create({
            'content_hash': '0x' + 'e'*64,
            'status': 'submitted',
            'tx_hash': '0xTxHash'
        })
        
        # Mock Receipt Success
        mock_w3.eth.get_transaction_receipt.return_value = {
            'status': 1,
            'blockNumber': 100
        }
        mock_w3.eth.get_block.return_value = {'timestamp': 1700000000}
        
        self.entry_model.check_transaction_receipts()
        
        self.assertEqual(entry.status, 'confirmed')

    def test_05_mixin_logic(self):
        """ Test the abstract mixin logic manually """
        # Create a dummy class on the fly inheriting the mixin
        # Not easily possible in Odoo tests without a real model. 
        # But we can verify the method exists and behaves.
        
        # Instead, let's verify duplicate hash logic
        h = '0xDuplicate'
        e1 = self.entry_model.create({'content_hash': h, 'status': 'confirmed'})
        
        # Constraint check
        with self.assertRaises(Exception): # PSQL IntegrityError usually
             self.entry_model.create({'content_hash': h})
