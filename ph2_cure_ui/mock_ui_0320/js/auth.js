// ===================== AUTHENTICATION =====================
const HARDCODED_CREDENTIALS = {
    email: 'ai@tiuconsulting.com',
    password: 'Admin@1234'
};

const currentUser = JSON.parse(localStorage.getItem('titlepro_user')) || null;

// Check authentication on page load
document.addEventListener('DOMContentLoaded', () => {
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    const publicPages = ['login.html', 'index.html', ''];

    if (!currentUser && !publicPages.includes(currentPage)) {
        window.location.href = 'login.html';
    } else if (currentUser && currentPage === 'login.html') {
        window.location.href = 'index.html';
    }
});

// Handle login
function handleLogin(event) {
    event.preventDefault();

    const email = document.getElementById('email')?.value || '';
    const password = document.getElementById('password')?.value || '';

    if (email === HARDCODED_CREDENTIALS.email && password === HARDCODED_CREDENTIALS.password) {
        const user = {
            email: email,
            name: 'Admin User',
            role: 'Admin',
            loginTime: new Date().toISOString()
        };

        localStorage.setItem('titlepro_user', JSON.stringify(user));
        window.location.href = 'index.html';
    } else {
        showError('Invalid email or password. Use ai@tiuconsulting.com / Admin@1234');
    }
}

function showError(message) {
    const errorDiv = document.getElementById('loginError');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

function handleLogout() {
    localStorage.removeItem('titlepro_user');
    window.location.href = 'login.html';
}

function getCurrentUser() {
    return JSON.parse(localStorage.getItem('titlepro_user')) || null;
}

// ===================== NAVIGATION =====================
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebar) {
        sidebar.classList.toggle('show');
    }
    if (overlay) {
        overlay.classList.toggle('show');
    }
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebar) {
        sidebar.classList.remove('show');
    }
    if (overlay) {
        overlay.classList.remove('show');
    }
}

function handleLogoClick(page) {
    closeSidebar();
    window.location.href = page;
    return false;
}

function toggleSettingsMenu() {
    const settingsToggle = document.getElementById('settingsToggle');
    const settingsSubmenu = document.getElementById('settingsSubmenu');

    if (settingsToggle && settingsSubmenu) {
        settingsToggle.classList.toggle('open');
        settingsSubmenu.classList.toggle('open');
    }
}

// Set active nav item
function setActiveNav(pageId) {
    document.querySelectorAll('.sidebar-nav-item').forEach(item => {
        item.classList.remove('active');
    });

    const activeItem = document.getElementById(pageId);
    if (activeItem) {
        activeItem.classList.add('active');
    }
}

// Update user info in page
function updateUserInfo() {
    const user = getCurrentUser();
    if (!user) return;

    const initials = user.name
        .split(' ')
        .map(n => n[0])
        .join('')
        .toUpperCase();

    const avatarEls = document.querySelectorAll('.user-avatar');
    avatarEls.forEach(el => {
        el.textContent = initials;
    });

    const userNameEl = document.getElementById('currentUserName');
    if (userNameEl) {
        userNameEl.textContent = user.name;
    }
}

// Initialize page
document.addEventListener('DOMContentLoaded', () => {
    updateUserInfo();
});
