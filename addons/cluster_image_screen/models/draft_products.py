from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

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

    @api.model
    def _default_cluster_head_user(self):
        cluster_head_group = self.env.ref('cluster_image_screen.cluster_head')
        if cluster_head_group in self.env.user.groups_id:
            return self.env.user.id
        return False
    
    @api.model
    def _get_cluster_head_domain(self):
        cluster_head_group = self.env.ref('cluster_image_screen.cluster_head') # IMP: Assuming 'cluster_image_screen.cluster_head' is the XML ID of the cluster head group
        return [('groups_id', 'in', [cluster_head_group.id])]
    
    clusterHeadUserId = fields.Many2one('res.users', string='Cluster Head User', required=True, domain=lambda self: self._get_cluster_head_domain(),default=_default_cluster_head_user)
    submit_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Submit Status', default='draft')
    def action_approve_product(self):
        for record in self:
            if record.submit_status != 'draft':
                raise ValidationError("You can only submit draft records.")

            required_fields = [
                ('productName', 'Product Name'),
                ('productCategory', 'Product Category'),
                ('clusterHeadUserId', 'Cluster Head'),
            ]
            missing = [label for field, label in required_fields if not getattr(record, field)]
            if missing:
                raise ValidationError(f"Please fill all required fields before submitting: {', '.join(missing)}.")

            record.submit_status = 'submitted'
