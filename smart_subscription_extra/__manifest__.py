{
    'name': 'Smart - Suscripciones Avanzadas',
    'version': '18.0.1.0.0',
    'summary': 'Extensión de suscripciones: modalidad pre/post pago, integración GCP y mora.',
    'author': 'Smart Business',
    'category': 'Accounting/Subscriptions',
    'depends': ['sale_subscription', 'l10n_gt_sb_extra', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/sale_subscription_views.xml',
        'views/late_fee_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
