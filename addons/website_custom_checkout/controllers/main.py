from odoo import http
from odoo.http import request, route
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command

class CustomWebsiteSale(WebsiteSale):

    @http.route(['/shop/cart'], type='http', auth='public', website=True, sitemap=False)
    def cart(self, access_token=None, revive='', **post):
        """
        Overrides the original /shop/cart endpoint.
        Fetches the current cart (sale.order) and passes it to the custom template.
        """
        # Get the current sale order (cart) from the standard website utility
        # order = http.request.website.sale_get_order()
        
        # # Prepare the rendering values, including the order object
        # values = {
        #     'order': order,
        #     'suggested_products': [], # Optional: You can add suggestions here if needed
        #     'website_sale_order': order, # Use the standard key for compatibility
        # }
        
        # # Render the custom template, passing the cart data


        if not request.website.has_ecommerce_access():
            return request.redirect('/web/login')

        order = request.website.sale_get_order()
        if order and order.state != 'draft':
            request.session['sale_order_id'] = None
            order = request.website.sale_get_order()

        request.session['website_sale_cart_quantity'] = order.cart_quantity

        values = {}
        if access_token:
            abandoned_order = request.env['sale.order'].sudo().search([('access_token', '=', access_token)], limit=1)
            if not abandoned_order:  # wrong token (or SO has been deleted)
                raise NotFound()
            if abandoned_order.state != 'draft':  # abandoned cart already finished
                values.update({'abandoned_proceed': True})
            elif revive == 'squash' or (revive == 'merge' and not request.session.get('sale_order_id')):  # restore old cart or merge with unexistant
                request.session['sale_order_id'] = abandoned_order.id
                return request.redirect('/shop/cart')
            elif revive == 'merge':
                abandoned_order.order_line.write({'order_id': request.session['sale_order_id']})
                abandoned_order.action_cancel()
            elif abandoned_order.id != request.session.get('sale_order_id'):  # abandoned cart found, user have to choose what to do
                values.update({'access_token': abandoned_order.access_token})

        values.update({
            'website_sale_order': order,
            'date': fields.Date.today(),
            'suggested_products': [],
        })
        if order:
            order.order_line.filtered(lambda sol: sol.product_id and not sol.product_id.active).unlink()
            values['suggested_products'] = order._cart_accessories()
            values.update(self._get_express_shop_payment_values(order))

        print(order,' ',order.website_order_line)
        values.update(self._cart_values(**post))    
        return http.request.render("website_custom_checkout.custom_cart_with_products", values)