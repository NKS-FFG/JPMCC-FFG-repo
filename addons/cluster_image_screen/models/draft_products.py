from odoo import fields, models, api, _

class ClusterDraftProducts(models.Model):
    _name = 'cluster.draft.products'
    _description = 'Cluster Draft Products'

    productName = fields.Char(string='Draft Product Name', required=True)
    description = fields.Char(string='Description')
    image = fields.Many2many('ir.attachment', string="Image")
    productCategory = fields.Many2one('product.public.category', string='Product Category', required=True)
    covering_material = fields.Char(string='Covering Material')
    dimensions = fields.Char(string='Dimensions')
    other_comments = fields.Text(string='Other Comments')
    tentative_price = fields.Float(string='Tentative Price')
    clusterHeadUserId = fields.Many2one('res.users', string='Cluster Head User', required=True, domain=lambda self: self._get_cluster_head_domain())

    @api.model
    def _get_cluster_head_domain(self):
        cluster_head_group = self.env.ref('Cluster_head_user_group.cluster_head') # IMP: Assuming 'Cluster_head_user_group.cluster_head' is the XML ID of the cluster head group
        return [('groups_id', 'in', [cluster_head_group.id])]
    
    submit_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Submit Status', default='draft')
    def action_approve_product(self):
        for record in self:
            record.submit_status = 'submitted'
