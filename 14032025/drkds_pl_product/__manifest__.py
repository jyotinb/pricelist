{
    'name': 'Product Costing',
    'version': '17.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Add detailed costing fields to products',
    'description': """
        This module adds the following costing fields to products:
        * Total Jobwork Cost
        * Total Freight Cost
        * Total Packing Cost
        * Cushion
        * Gross Profit
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['product', 'base'],  # Ensure base module is loaded for security
    'data': [
        'security/product_costing_security.xml',
        'security/ir.model.access.csv',
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
