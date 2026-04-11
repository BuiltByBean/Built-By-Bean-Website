// Enable JS-only styling (fade-on-scroll, etc). If this script fails
// to load or errors out, the page stays fully visible without dimming.
document.documentElement.classList.add('js-ready');

// Navigation scroll effect
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 20);
});

// Mobile nav toggle
const navToggle = document.getElementById('nav-toggle');
const navLinks = document.getElementById('nav-links');

navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
});

// Close mobile nav on link click
navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
        navLinks.classList.remove('open');
    });
});

// Scroll animations for cards (fade-in once)
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -40px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('fade-in');
            observer.unobserve(entry.target);
        }
    });
}, observerOptions);

document.querySelectorAll('.service-card, .process-step, .contact-card, .about-content').forEach(el => {
    observer.observe(el);
});

// Section visibility — fade the active section in, dim the others.
// Reversible (no unobserve) so sections fade out when scrolled past.
const sectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        entry.target.classList.toggle('is-visible', entry.intersectionRatio >= 0.35);
    });
}, {
    threshold: [0, 0.15, 0.35, 0.55, 0.75, 1]
});

document.querySelectorAll('.hero, .section').forEach(el => {
    sectionObserver.observe(el);
});

// Mark the hero visible immediately on load so the first view isn't dim
const hero = document.querySelector('.hero');
if (hero) hero.classList.add('is-visible');

// Contact form
const form = document.getElementById('contact-form');
const submitBtn = document.getElementById('submit-btn');
const formStatus = document.getElementById('form-status');

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const data = {
        name: form.name.value,
        email: form.email.value,
        project_type: form.project_type.value,
        message: form.message.value,
    };

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';
    formStatus.className = 'form-status';
    formStatus.textContent = '';

    try {
        const res = await fetch('/api/contact', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        const result = await res.json();

        if (res.ok) {
            formStatus.className = 'form-status success';
            formStatus.textContent = result.message;
            form.reset();
        } else {
            formStatus.className = 'form-status error';
            formStatus.textContent = result.error;
        }
    } catch {
        formStatus.className = 'form-status error';
        formStatus.textContent = 'Network error. Please email me directly at mbean@builtbybeans.com';
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send Message';
    }
});
