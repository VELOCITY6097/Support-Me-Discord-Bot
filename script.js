// Scroll animations
const scrollElements = document.querySelectorAll('.scroll-animate');

const handleScroll = () => {
    scrollElements.forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.top <= window.innerHeight * 0.8) {
            el.classList.add('visible');
        }
    });
};

window.addEventListener('scroll', handleScroll);

// Trigger animations on load for initial elements
handleScroll();
