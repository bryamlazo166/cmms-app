window.onload = function () {
    const sidebar = document.querySelector(".sidebar");
    const closeBtn = document.querySelector("#btn_toggle");

    // Create overlay if not exists
    let overlay = document.getElementById('sidebar-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'sidebar-overlay';
        document.body.appendChild(overlay);

        overlay.addEventListener('click', () => {
            sidebar.classList.remove("open");
            overlay.classList.remove("active");
            menuBtnChange();
        });
    }

    closeBtn.addEventListener("click", () => {
        sidebar.classList.toggle("open");
        overlay.classList.toggle("active");
        menuBtnChange();
    });

    function menuBtnChange() {
        if (sidebar.classList.contains("open")) {
            closeBtn.classList.replace("fa-bars", "fa-times"); // Change to X when open
        } else {
            closeBtn.classList.replace("fa-times", "fa-bars");
        }
    }

    // Highlight Active Link
    const path = window.location.pathname;
    const links = document.querySelectorAll('.nav-list li a');
    links.forEach(link => {
        const href = link.getAttribute('href');
        if (href === '/' && path === '/') {
            link.classList.add('active');
        } else if (href !== '/' && path.startsWith(href)) {
            link.classList.add('active');
        }
    });
}
