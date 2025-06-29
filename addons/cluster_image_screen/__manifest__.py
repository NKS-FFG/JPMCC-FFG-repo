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
        'base', 'website', 'website_sale'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/draft_products.xml'
    ],
    'installable': True,
    'application': True,
}