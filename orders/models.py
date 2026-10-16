import secrets
import uuid
from pathlib import Path
from django.conf import settings
from django.db import models
from django.utils import timezone


class VectorJob(models.Model):
    """
    Stores server-side LightBurn SVG generation sessions.
    The raw SVG is saved inside settings.PRIVATE_SVG_ROOT and is never
    exposed publicly unless an admin downloads it or a valid one-time
    digital license token is redeemed.
    """

    MATERIAL_CHOICES = [
        ('slate', 'Natural Slate Coaster'),
        ('mdf', 'Laser Cut MDF / Birch'),
        ('acrylic', 'Edge-Lit Acrylic'),
    ]

    job_id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    original_filename = models.CharField(max_length=255, blank=True)
    private_svg_filename = models.CharField(max_length=255)
    custom_text = models.CharField(max_length=80, blank=True)
    selected_material = models.CharField(
        max_length=32, choices=MATERIAL_CHOICES, default='slate'
    )
    customer_email = models.EmailField(blank=True)
    is_digital_paid = models.BooleanField(default=False)
    download_token = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    token_expires_at = models.DateTimeField(null=True, blank=True)
    token_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'LightBurn Vector Job'
        verbose_name_plural = 'LightBurn Vector Jobs'

    def __str__(self):
        return f"VectorJob {str(self.job_id)[:8]} ({self.original_filename or 'Upload'})"

    def get_svg_path(self) -> Path:
        return Path(settings.PRIVATE_SVG_ROOT) / self.private_svg_filename

    def issue_one_time_token(self, hours_valid: int = 24):
        self.download_token = uuid.uuid4()
        self.token_expires_at = timezone.now() + timezone.timedelta(hours=hours_valid)
        self.token_used = False
        self.is_digital_paid = True
        self.save(
            update_fields=[
                'download_token',
                'token_expires_at',
                'token_used',
                'is_digital_paid',
            ]
        )

    def is_token_valid(self) -> bool:
        if not self.is_digital_paid or self.token_used:
            return False
        if self.token_expires_at and timezone.now() > self.token_expires_at:
            return False
        return self.get_svg_path().is_file()


class CommissionOrder(models.Model):
    """
    Stores physical and custom engraving orders for Pauly Bruv Engraving.
    Orders land in the admin dashboard so Paul can review the design,
    download the linked LightBurn SVG, and send a PayPal payment link.
    """

    PRODUCT_CHOICES = [
        ('photo_engraving', 'Custom Photo Laser Engraving'),
        ('street_sign', '3D Layered MDF Street Sign'),
        ('tactical_coaster', 'Tactical Football Slate Coasters'),
        ('brummie_magnet', 'Brummie Slang Wood Magnets'),
        ('business_display', 'B2B / Market Stall QR Stand & Display'),
        ('man_cave_bundle', 'Man Cave Bundle (Street Sign + 4 Coasters)'),
        ('digital_svg', 'Digital LightBurn SVG License (£4.99)'),
        ('custom_quote', 'Bespoke Commission / Quote Request'),
    ]

    FULFILLMENT_CHOICES = [
        ('uk_delivery', 'UK Tracked Postage (£3.50)'),
        ('birmingham_collection', 'Free Local Collection (Chelmsley Wood, B37)'),
        ('digital_download', 'Instant Digital SVG Download'),
    ]

    STATUS_CHOICES = [
        ('new_inquiry', 'New Order — Send PayPal Link'),
        ('paypal_sent', 'PayPal Link Sent — Awaiting Payment'),
        ('paid_in_queue', 'Paid — Ready for LightBurn / Laser'),
        ('engraving', 'In Workshop — Laser Engraving'),
        ('completed', 'Completed / Dispatched'),
        ('cancelled', 'Cancelled'),
    ]

    order_reference = models.CharField(
        max_length=20, unique=True, editable=False, db_index=True
    )
    customer_name = models.CharField(max_length=120)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=40, blank=True)
    product_category = models.CharField(
        max_length=40, choices=PRODUCT_CHOICES, default='photo_engraving'
    )
    material = models.CharField(max_length=60, blank=True)
    size_option = models.CharField(max_length=80, blank=True)
    finish_option = models.CharField(max_length=80, blank=True)
    custom_text = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    fulfillment_type = models.CharField(
        max_length=30, choices=FULFILLMENT_CHOICES, default='uk_delivery'
    )
    delivery_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    estimated_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=0.00
    )
    paypal_link_sent = models.BooleanField(
        default=False, help_text='Tick once you have sent the customer their PayPal link'
    )
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='new_inquiry'
    )
    vector_job = models.ForeignKey(
        VectorJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text='Linked server-side LightBurn SVG job (if created via Photo Vectorizer)',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Commission Order'
        verbose_name_plural = 'Commission Orders'

    def save(self, *args, **kwargs):
        if not self.order_reference:
            token = secrets.token_hex(3).upper()
            self.order_reference = f"PBE-{token}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_reference} - {self.customer_name} ({self.get_product_category_display()})"
