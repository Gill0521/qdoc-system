// assets/js/main.js

document.addEventListener('DOMContentLoaded', function() {
    
    // 1. Check if AOS library is loaded
    if (typeof AOS !== 'undefined') {
        AOS.init({
            duration: 1000,
            once: true,
        });
    } else {
        console.warn("AOS Library was not found. Animations disabled.");
    }

    // 2. Any other custom JS code you have can go here...
    
});