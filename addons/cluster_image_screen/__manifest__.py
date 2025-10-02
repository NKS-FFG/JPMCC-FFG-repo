{
    'name': 'Cluster Draft Products', 
    'summary': 'Cluster Head Draft Product Image Screen',
    'description': '''
        Cluster Head Draft Product Image Screen
    ''',
    'version': '18.0.1.0.0',
    'category': 'Website/Website',
    'license': 'LGPL-3', 
    'author': 'JPMCC FFG',
    'website': '',
    'depends': [
        'base', 'website', 'website_sale', 'product'
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'security/ir.rule.xml',
        'views/draft_products.xml',
        'views/product_template_view.xml'
    ],
    'installable': True,
    'application': True,
}