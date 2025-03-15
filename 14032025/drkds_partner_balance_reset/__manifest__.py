# __manifest__.py
{
    'name': 'Partner Balance Reset',
    'version': '1.0',
    'summary': 'Reset partner balances in bulk using CSV',
    'description': """
        This module allows you to reset partner balances in bulk using a CSV file.
        It provides a wizard to upload a CSV file with partner information and
        reset their balances as of a specific date.
    """,
    'category': 'Accounting',
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['base', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/partner_balance_wizard_views.xml',
        'views/partner_balance_reset_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}