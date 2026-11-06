import re
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Profile

class CustomRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label="Email address",
        widget=forms.EmailInput(attrs={'placeholder': 'your.email@example.com'})
    )
    phone_number = forms.CharField(
        required=True,
        max_length=15,
        label="Mobile Number",
        widget=forms.TextInput(attrs={'type': 'tel', 'placeholder': 'Enter 10-digit mobile number'}),
        help_text="We'll send order tracking & delivery updates via SMS/WhatsApp."
    )

    class Meta:
        model = User
        fields = ['username', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Clear default verbose help texts so user has a clean, simple form
        if 'password1' in self.fields:
            self.fields['password1'].help_text = ''
            self.fields['password1'].widget.attrs.update({'placeholder': 'Create a password'})
        if 'password2' in self.fields:
            self.fields['password2'].help_text = ''
            self.fields['password2'].widget.attrs.update({'placeholder': 'Confirm your password'})
        if 'username' in self.fields:
            self.fields['username'].help_text = ''
            self.fields['username'].widget.attrs.update({'placeholder': 'Choose a username'})

        # Order fields: username, email, phone_number, password1, password2
        field_order = ['username', 'email', 'phone_number', 'password1', 'password2']
        self.order_fields([f for f in field_order if f in self.fields])

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check for existing users with this email, ignoring case
            if User.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean_phone_number(self):
        phone = (self.cleaned_data.get('phone_number') or '').strip()
        digits = re.sub(r'\D', '', phone)
        # Handle prefixes like +91 or 0
        if len(digits) == 12 and digits.startswith('91'):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]

        if len(digits) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit mobile number.")
        return digits

    def save(self, commit=True):
        user = super().save(commit=commit)
        phone = self.cleaned_data.get('phone_number')
        if commit and phone:
            Profile.objects.update_or_create(user=user, defaults={'phone_number': phone})
        return user

