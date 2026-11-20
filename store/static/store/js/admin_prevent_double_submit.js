(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var forms = document.querySelectorAll('form#product_form, form#productcolor_form, form#change_form, .change-form form');
        if (!forms.length) {
            forms = document.querySelectorAll('form');
        }
        forms.forEach(function (form) {
            var isSubmitting = false;
            form.addEventListener('submit', function (e) {
                if (isSubmitting) {
                    e.preventDefault();
                    return false;
                }
                isSubmitting = true;

                // Disable submit buttons after a tiny delay so Django receives which button (e.g. _save, _continue) was clicked
                setTimeout(function () {
                    var submitBtns = form.querySelectorAll('input[type="submit"], button[type="submit"]');
                    submitBtns.forEach(function (btn) {
                        btn.style.opacity = '0.5';
                        btn.style.pointerEvents = 'none';
                        if (btn.tagName === 'INPUT') {
                            btn.dataset.originalVal = btn.value;
                            btn.value = 'Saving... Please wait';
                        }
                    });
                }, 50);
            });
        });
    });
})();
