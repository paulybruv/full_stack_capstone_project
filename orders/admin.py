from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import path, reverse
from django.utils.html import format_html
from .models import CommissionOrder, VectorJob


@admin.register(VectorJob)
class VectorJobAdmin(admin.ModelAdmin):
    list_display = (
        'short_job_id',
        'original_filename',
        'selected_material',
        'custom_text',
        'is_digital_paid',
        'token_used',
        'download_svg_button',
        'created_at',
    )
    list_filter = ('selected_material', 'is_digital_paid', 'token_used', 'created_at')
    search_fields = ('job_id', 'original_filename', 'custom_text', 'customer_email')
    readonly_fields = (
        'job_id',
        'private_svg_filename',
        'download_token',
        'created_at',
        'download_svg_button',
    )

    def short_job_id(self, obj):
        return str(obj.job_id)[:8]

    short_job_id.short_description = 'Job ID'

    def download_svg_button(self, obj):
        if obj.pk and obj.get_svg_path().is_file():
            url = reverse('admin:orders_vectorjob_download_svg', args=[obj.pk])
            return format_html(
                '<a class="button" style="background:#0f172a;color:#fff;padding:4px 10px;border-radius:4px;" href="{}">'
                'Download LightBurn SVG</a>',
                url,
            )
        return 'Missing SVG'

    download_svg_button.short_description = 'LightBurn File'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:object_id>/download-svg/',
                self.admin_site.admin_view(self.admin_download_svg),
                name='orders_vectorjob_download_svg',
            ),
        ]
        return custom_urls + urls

    def admin_download_svg(self, request, object_id):
        job = self.get_object(request, object_id)
        if not job or not job.get_svg_path().is_file():
            raise Http404('LightBurn SVG file not found on server.')
        return FileResponse(
            open(job.get_svg_path(), 'rb'),
            as_attachment=True,
            filename=f"pauly_bruv_lightburn_{str(job.job_id)[:8]}.svg",
            content_type='image/svg+xml',
        )


@admin.register(CommissionOrder)
class CommissionOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_reference',
        'customer_name',
        'product_category',
        'material',
        'custom_text',
        'estimated_price',
        'status',
        'paypal_link_sent',
        'lightburn_svg_link',
        'created_at',
    )
    list_filter = (
        'status',
        'paypal_link_sent',
        'product_category',
        'fulfillment_type',
        'created_at',
    )
    list_editable = ('status', 'paypal_link_sent')
    search_fields = (
        'order_reference',
        'customer_name',
        'customer_email',
        'customer_phone',
        'custom_text',
    )
    readonly_fields = ('order_reference', 'created_at', 'lightburn_svg_link')

    def lightburn_svg_link(self, obj):
        if obj.vector_job and obj.vector_job.get_svg_path().is_file():
            url = reverse(
                'admin:orders_vectorjob_download_svg', args=[obj.vector_job.pk]
            )
            return format_html(
                '<a class="button" style="background:#0f172a;color:#fff;padding:4px 10px;border-radius:4px;" href="{}">'
                '⬇ LightBurn SVG</a>',
                url,
            )
        return '—'

    lightburn_svg_link.short_description = 'Production SVG'
