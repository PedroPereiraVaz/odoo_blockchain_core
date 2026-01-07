{
    'name': 'Odoo Blockchain Core',
    'version': '18.0.1.0.0',
    'category': 'Technical/Blockchain',
    'summary': 'Universal Blockchain Document Registry Core',
    'description': """
        Módulo núcleo para registrar huellas digitales de documentos en una blockchain EVM.
        Características:
        - Registro Universal (Hash)
        - Verificación y Revocación
        - Gestión de Gas y Colas de Transacciones
        - Uso de Variables de Entorno para máxima seguridad
    """,
    'author': 'Pedro',
    'depends': ['base', 'mail'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/verification_template.xml',
        'views/blockchain_registry_entry_views.xml',
        'views/blockchain_menu_views.xml',
    ],
    'external_dependencies': {
        'python': ['web3'],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
