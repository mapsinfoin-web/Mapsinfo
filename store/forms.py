from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class CustomRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Clear default verbose help texts so user has a clean, simple form
        if 'password1' in self.fields:
            self.fields['password1'].help_text = ''
        if 'password2' in self.fields:
            self.fields['password2'].help_text = ''
        if 'username' in self.fields:
            self.fields['username'].help_text = ''

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check for existing users with this email, ignoring case
            if User.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError("An account with this email address already exists.")
        return email
