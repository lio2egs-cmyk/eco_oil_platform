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

    /* ---------- Portal entry dropdown (כניסת לקוחות) ---------- */
    const portalEntry = document.querySelector('.portal-entry');
    if (portalEntry) {
        const portalBtn  = portalEntry.querySelector('.portal-btn');
        const portalMenu = portalEntry.querySelector('.portal-menu');
        const setPortalOpen = (open) => {
            portalMenu.classList.toggle('open', open);
            portalBtn.setAttribute('aria-expanded', String(open));
            portalMenu.setAttribute('aria-hidden', String(!open));
        };
        portalBtn.addEventListener('click', e => {
            e.stopPropagation();
            setPortalOpen(!portalMenu.classList.contains('open'));
        });
        document.addEventListener('click', e => {
            if (!portalEntry.contains(e.target)) setPortalOpen(false);
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') setPortalOpen(false);
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

            // Submit to Netlify Forms via AJAX
            const btn = form.querySelector('.btn-submit');
            btn.disabled = true;
            btn.textContent = 'שולח...';

            fetch('/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams(new FormData(form)).toString()
            })
            .then(response => {
                if (!response.ok) throw new Error('Submission failed');
                form.reset();
                if (successMsg) {
                    successMsg.hidden = false;
                    successMsg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    setTimeout(() => { successMsg.hidden = true; }, 6000);
                }
            })
            .catch(() => {
                alert('אירעה שגיאה בשליחת הטופס. נסו שוב או צרו קשר טלפונית.');
            })
            .finally(() => {
                btn.disabled = false;
                btn.textContent = 'שלח';
            });
        });

        // Clear invalid state on input
        form.addEventListener('input', e => {
            e.target.classList.remove('invalid');
        });
    }

    /* ---------- Depot contact form ---------- */
    const depotForm       = document.getElementById('depotContactForm');
    const depotSuccessMsg = document.getElementById('depotFormSuccess');

    if (depotForm) {
        depotForm.addEventListener('submit', e => {
            e.preventDefault();
            let valid = true;

            const required = depotForm.querySelectorAll('[required]');
            required.forEach(field => {
                field.classList.remove('invalid');
                if (!field.value.trim()) {
                    field.classList.add('invalid');
                    valid = false;
                }
            });

            const emailField = depotForm.querySelector('[type="email"]');
            if (emailField && emailField.value.trim()) {
                const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRe.test(emailField.value.trim())) {
                    emailField.classList.add('invalid');
                    valid = false;
                }
            }

            if (!valid) return;

            // Submit to Netlify Forms via AJAX
            const btn = depotForm.querySelector('.btn-submit');
            btn.disabled = true;
            btn.textContent = 'שולח...';

            fetch('/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams(new FormData(depotForm)).toString()
            })
            .then(response => {
                if (!response.ok) throw new Error('Submission failed');
                depotForm.reset();
                if (depotSuccessMsg) {
                    depotSuccessMsg.hidden = false;
                    depotSuccessMsg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    setTimeout(() => { depotSuccessMsg.hidden = true; }, 6000);
                }
            })
            .catch(() => {
                alert('אירעה שגיאה בשליחת הטופס. נסו שוב או צרו קשר טלפונית.');
            })
            .finally(() => {
                btn.disabled = false;
                btn.textContent = 'שלח פנייה';
            });
        });

        depotForm.addEventListener('input', e => {
            e.target.classList.remove('invalid');
        });
    }

    /* ---------- Certificate lightbox (eco-depot) ---------- */
    const certLightbox = document.getElementById('certLightbox');
    if (certLightbox) {
        const lbContent = certLightbox.querySelector('.cert-lightbox-content');
        const lbImg     = document.getElementById('certLightboxImg');
        const lbGallery = document.getElementById('certLightboxGallery');
        const lbPages   = document.getElementById('certLightboxPages');
        const lbTitle   = document.getElementById('certLightboxTitle');
        const triggers  = document.querySelectorAll('[data-cert-img], [data-cert-images], [data-cert-pages]');

        const resetModes = () => {
            lbImg.hidden = true; lbImg.src = '';
            lbGallery.hidden = true; lbGallery.innerHTML = '';
            lbPages.hidden = true; lbPages.innerHTML = '';
            lbContent.classList.remove('cert-lightbox-content--gallery', 'cert-lightbox-content--pages');
        };
        const openSingle = (src, title) => {
            resetModes();
            lbImg.src = src;
            lbImg.alt = title || '';
            lbImg.hidden = false;
        };
        const openGallery = (sources, title) => {
            resetModes();
            sources.forEach(src => {
                const im = document.createElement('img');
                im.src = src;
                im.alt = title || '';
                im.loading = 'lazy';
                lbGallery.appendChild(im);
            });
            lbGallery.hidden = false;
            lbContent.classList.add('cert-lightbox-content--gallery');
        };
        const openPages = (sources, title) => {
            resetModes();
            const counter = document.createElement('div');
            counter.className = 'cert-lightbox-pages-counter';
            counter.textContent = sources.length + ' pages';
            lbPages.appendChild(counter);
            sources.forEach((src, i) => {
                const im = document.createElement('img');
                im.src = src;
                im.alt = (title || '') + ' — page ' + (i + 1);
                im.loading = 'lazy';
                lbPages.appendChild(im);
            });
            lbPages.hidden = false;
            lbContent.classList.add('cert-lightbox-content--pages');
            lbContent.scrollTop = 0;
        };
        const openLightbox = (btn) => {
            lbTitle.textContent = btn.dataset.certTitle || '';
            if (btn.dataset.certPages) {
                const list = btn.dataset.certPages.split('|').map(s => s.trim()).filter(Boolean);
                openPages(list, btn.dataset.certTitle);
            } else if (btn.dataset.certImages) {
                const list = btn.dataset.certImages.split('|').map(s => s.trim()).filter(Boolean);
                openGallery(list, btn.dataset.certTitle);
            } else if (btn.dataset.certImg) {
                openSingle(btn.dataset.certImg, btn.dataset.certTitle);
            }
            certLightbox.hidden = false;
            document.body.style.overflow = 'hidden';
        };
        const closeLightbox = () => {
            certLightbox.hidden = true;
            document.body.style.overflow = '';
            resetModes();
        };

        triggers.forEach(btn => {
            btn.addEventListener('click', () => openLightbox(btn));
        });
        certLightbox.querySelectorAll('[data-cert-close]').forEach(el => {
            el.addEventListener('click', closeLightbox);
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && !certLightbox.hidden) closeLightbox();
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
