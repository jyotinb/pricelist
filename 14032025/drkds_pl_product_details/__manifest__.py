{
    'name': 'BOM Cost Calculator Detail View',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Adds detailed cost breakdown for products in multi-product calculator',
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['drkds_pl2',],  # Use your actual module name here
    'data': [
        'security/ir.model.access.csv',
        'views/product_cost_details_wizard_view.xml',
        'views/bom_cost_calculator_views_modified.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}