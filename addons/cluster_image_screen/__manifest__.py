{
    'name': 'first module', 
    'summary': 'First Odoo 18 module',
    'description': '''
        Testing Purpuses.
    ''',
    'version': '18.0.1.0.0',
    'category': 'Website/Website',
    'license': 'LGPL-3', 
    'author': 'Odooistic',
    'website': 'http://www.odooistic.co.uk',
    'depends': [
        'base', 'website'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/first_module_views.xml',
        'views/hello_world_template.xml',
        'views/menu.xml',
    ],
    
    'installable': True,
    'application': True,

}