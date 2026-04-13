/* ============================================================
   ECO-OIL WEBSITE – script.js
   ============================================================ */

(function () {
    'use strict';

    /* ---------- Mobile menu ---------- */
    const hamburger  = document.getElementById('hamburger');
    const mobileMenu = document.getElementById('mobileMenu');

    if (hamburger && mobileMenu) {
        hamburger.addEventListener('click', () => {
            const isOpen = mobileMenu.classList.toggle('open');
            hamburger.classList.toggle('open', isOpen);
            hamburger.setAttribute('aria-expanded', String(isOpen));
            mobileMenu.setAttribute('aria-hidden', String(!isOpen));
        });

        // Close menu when any link inside it is clicked
        mobileMenu.querySelectorAll('[data-close]').forEach(link => {
            link.addEventListener('click', () => {
                mobileMenu.classList.remove('open');
                hamburger.classList.remove('open');
                hamburger.setAttribute('aria-expanded', 'false');
                mobileMenu.setAttribute('aria-hidden', 'true');
            });
        });

        // Close menu on outside click
        document.addEventListener('click', e => {
            if (!hamburger.contains(e.target) && !mobileMenu.contains(e.target)) {
                mobileMenu.classList.remove('open');
                hamburger.classList.remove('open');
                hamburger.setAttribute('aria-expanded', 'false');
                mobileMenu.setAttribute('aria-hidden', 'true');
            }
        });
    }

    /* ---------- Sticky header shrink ---------- */
    const header = document.querySelector('.site-header');
    if (header) {
        window.addEventListener('scroll', () => {
            header.classList.toggle('scrolled', window.scrollY > 60);
        }, { passive: true });
    }

    /* ---------- Contact form ---------- */
    const form        = document.getElementById('contactForm');
    const successMsg  = document.getElementById('formSuccess');

    if (form) {
        form.addEventListener('submit', e => {
            e.preventDefault();
            let valid = true;

            // Simple validation: required fields
            const required = form.querySelectorAll('[required]');
            required.forEach(field => {
                field.classList.remove('invalid');
                if (!field.value.trim()) {
                    field.classList.add('invalid');
                    valid = false;
                }
            });

            // Email format check
            const emailField = form.querySelector('#email');
            if (emailField && emailField.value.trim()) {
                const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRe.test(emailField.value.trim())) {
                    emailField.classList.add('invalid');
                    valid = false;
                }
            }

            if (!valid) return;

            // Simulate successful submission
            const btn = form.querySelector('.btn-submit');
            btn.disabled = true;
            btn.textContent = 'שולח...';

            setTimeout(() => {
                form.reset();
                btn.disabled = false;
                btn.textContent = 'שלח';
                if (successMsg) {
                    successMsg.hidden = false;
                    successMsg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    setTimeout(() => { successMsg.hidden = true; }, 6000);
                }
            }, 900);
        });

        // Clear invalid state on input
        form.addEventListener('input', e => {
            e.target.classList.remove('invalid');
        });
    }

    /* ---------- Smooth scroll for anchor links ---------- */
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', e => {
            const targetId = anchor.getAttribute('href').slice(1);
            if (!targetId) return;
            const target = document.getElementById(targetId);
            if (target) {
                e.preventDefault();
                const headerH = header ? header.offsetHeight : 0;
                const top = target.getBoundingClientRect().top + window.scrollY - headerH - 10;
                window.scrollTo({ top, behavior: 'smooth' });
            }
        });
    });

    /* ---------- Fade-in on scroll ---------- */
    const fadeEls = document.querySelectorAll(
        '.about-text, .service-card, .why-us-content p, .why-us-logo-block'
    );

    if ('IntersectionObserver' in window) {
        fadeEls.forEach(el => {
            el.style.opacity = '0';
            el.style.transform = 'translateY(18px)';
            el.style.transition = 'opacity .5s ease, transform .5s ease';
        });

        const io = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });

        fadeEls.forEach(el => io.observe(el));
    }

})();
