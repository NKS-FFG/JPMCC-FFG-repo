from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError
import base64
import requests

class ClusterMatchResult(models.Model):
    _name = 'cluster.match.result'
    _description = 'Similarity Match Result'

    cluster_product_id = fields.Many2one('cluster.draft.products', string="Draft Product", ondelete='cascade')
    similarity = fields.Float(string="Similarity")
    match_id = fields.Many2one('ir.attachment', string="Matched Image")
    image_url = fields.Char(string="Image URL", compute='_compute_image_url')
    filename = fields.Char(string="Match") 
    image_display = fields.Html(string="Image Preview", compute='_compute_image_display')

    @api.depends('match_id')
    def _compute_image_url(self):
        for record in self:
            if record.match_id:
                record.image_url = f'/web/content/{record.match_id.id}'
            else:
                record.image_url = ''

    @api.depends('image_url')
    def _compute_image_display(self):
        for record in self:
            if record.image_url:
                record.image_display = f'<img src="{record.image_url}" alt="Product Image" style="max-width: 100px; max-height: 100px; border-radius: 5px;"/>'
            else:
                record.image_display = ''

class ClusterDraftProducts(models.Model):
    _name = 'cluster.draft.products'
    _description = 'Cluster Draft Products'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    productName = fields.Char(string='Draft Product Name', required=True, tracking=True)
    description = fields.Char(string='Description', tracking=True)

    product_template_image_ids = fields.One2many(
        string="Product Images",
        comodel_name='product.image',
        inverse_name='draft_product_id',
        copy=True,
        required=True
    )


    # main_image = fields.Binary("Main Image", compute='_compute_main_image', store=True)

    cluster_product_id = fields.Many2one('cluster.draft.products', string="Product", ondelete='cascade')
    match_ids = fields.One2many('cluster.match.result', 'cluster_product_id', string="Similarity Matches")

    productCategory = fields.Many2one('product.public.category', string='Product Category', required=True, tracking=True)
    covering_material = fields.Char(string='Covering Material', tracking=True)
    dimensions = fields.Char(string='Dimensions', tracking=True)
    other_remarks = fields.Text(string='Other Remarks', tracking=True)
    tentative_price = fields.Float(string='Tentative Price', tracking=True)

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
    
    clusterHeadUserId = fields.Many2one('res.users', 
        string='Cluster Head User', 
        required=True, 
        domain=lambda self: self._get_cluster_head_domain(),
        default=_default_cluster_head_user,
        tracking=True
    )
    submit_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Submit Status', default='draft', tracking=True)
    def action_approve_product(self):
        for record in self:
            if record.submit_status != 'draft':
                raise ValidationError("You can only submit draft records.")

            required_fields = [
                ('productName', 'Product Name'),
                ('productCategory', 'Product Category'),
                ('clusterHeadUserId', 'Cluster Head'),
                ('product_template_image_ids', 'Product Images')
            ]
            missing = [label for field, label in required_fields if not getattr(record, field)]
            if missing:
                raise ValidationError(f"Please fill all required fields before submitting: {', '.join(missing)}.")

            record.submit_status = 'submitted'

    is_submit_button_disabled = fields.Boolean(compute='_compute_editability',default=False,
        store=False
    )
    is_approve_button_invisible = fields.Boolean(compute='_compute_editability', store=False, default=True)
    is_compare_button_invisible = fields.Boolean(compute='_compute_editability', store=False, default=True)
    is_similarity_result_invisible = fields.Boolean(compute='_compute_editability', default=True, store=False)
    form_readonly = fields.Boolean(compute='_compute_editability', store=False)

    @api.depends()
    def _compute_editability(self):
        for rec in self:
            rec.form_readonly = True
            rec.is_submit_button_disabled = True
            rec.is_approve_button_invisible = True
            rec.is_compare_button_invisible = True
            rec.is_similarity_result_invisible = True

            if rec.submit_status == 'draft':
                rec.form_readonly = False
                rec.is_submit_button_disabled = False
                rec.is_approve_button_invisible = True
            elif rec.submit_status == 'approved' or rec.submit_status == 'rejected':
                rec.is_approve_button_invisible = True
                rec.form_readonly = True
            elif self.env.user.has_group('cluster_image_screen.cluster_head'):
                rec.form_readonly = True
            elif self.env.user.has_group('cluster_image_screen.cluster_reviewer') or self.env.user.has_group('base.group_system') :
                rec.form_readonly = False
                rec.is_approve_button_invisible = False
                rec.is_compare_button_invisible = False
                rec.is_similarity_result_invisible = False

    def convert_to_ecommerce_product(self):
        for draft in self:
            if draft.submit_status != 'submitted':
                raise ValidationError("Only approved draft products can be published to eCommerce.")

            if not draft.product_template_image_ids:
                raise ValidationError("At least one image is required to publish the product.")

            # Use the first image as the main product image
            main_image1 = draft.product_template_image_ids[0]

            product_vals = {
                'name': draft.productName,
                'description_ecommerce': draft.description,
                'website_published': True,
                'public_categ_ids': [(6, 0, [draft.productCategory.id])],
                'sale_ok': True,
                'list_price': draft.tentative_price or 0.0,
                'categ_id': self.env.ref('product.product_category_all').id,
                'image_1920': main_image1.image_1920,
                'dimensions':draft.dimensions,
                'other_remarks': draft.other_remarks,
                'covering_material': draft.covering_material
            }

            product = self.env['product.template'].create(product_vals)

            # main_image1.write({
            #     'product_tmpl_id': product.id
            # })
             # Copy additional images (excluding the first one that's already set as main image)
            for image in draft.product_template_image_ids[1:]:
                image.write({
                    'product_tmpl_id': product.id
                })
            
            # Optional: update status or mark draft as converted
            draft.write({'submit_status': 'approved'})  # Add 'published' if needed
    
    def reject_product(self):
        for record in self:
            record.submit_status = 'rejected'
            record.is_approve_button_invisible = False
            record.form_readonly = True

    def compare_button(self):
        for record in self:
            if not record.image:
                raise UserError("Please upload an image to compare.")

            # Send the first image only
            attachment = record.image[0]
            print("Attachment details:", attachment)
            image_binary = base64.b64decode(attachment.datas)
            files = {'image': (attachment.name, image_binary, attachment.mimetype)}

            try:
                response = requests.post('http://localhost:5001/compare', files=files)
                response.raise_for_status()
                data = response.json()

                # Save the result in a text field
                # result_lines = [f"Match: {m['filename']}, Similarity: {m['similarity']:.4f}, ID: {m['id']}" for m in data.get('top_matches', [])]
                # record.similarity_result = '\n'.join(result_lines)

                matches = []
                for match in data.get('top_matches', []):
                    matches.append((0, 0, {
                        'filename': match['filename'],
                        'similarity': match['similarity'],
                        'match_id': match['id'],
                    }))

                record.match_ids = [(5, 0, 0)] + matches 
                print("Comparison results:", matches)
                print("record.match_ids:", record.match_ids)

                for match in record.match_ids:
                    print("Filename:", match.filename)
                    print("Similarity:", match.similarity)
                    print("Image URL:", match.image_url)
                    print("Attachment ID:", match.match_id.id)

            except Exception as e:
                raise UserError(f"Error during comparison: {str(e)}")


class ProductImage(models.Model):
    _inherit = 'product.image'

    draft_product_id = fields.Many2one(
        'cluster.draft.products',
        string='Draft Product',
        ondelete='cascade'
    )

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    covering_material = fields.Char(string='Covering Material', tracking=True)
    dimensions = fields.Char(string='Dimensions', tracking=True)
    other_remarks = fields.Text(string='Other Remarks', tracking=True)


