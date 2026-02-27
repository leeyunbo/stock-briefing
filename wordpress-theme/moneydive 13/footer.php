<footer class="site-footer">
    <div class="footer-inner">
        <div class="footer-disclaimer">
            본 사이트의 모든 콘텐츠는 정보 제공 목적이며, 특정 금융 상품에 대한 투자 권유가 아닙니다. 투자 판단의 책임은 본인에게 있으며, 투자 전 반드시 전문가와 상담하시기 바랍니다.
        </div>
        <div class="footer-links">
            <a href="/privacy-policy/">개인정보처리방침</a>
            <span class="footer-links-sep">|</span>
            <a href="/about/">사이트 소개</a>
        </div>
        <div class="footer-copyright">
            &copy; <?php echo date('Y'); ?> 머니다이브. All rights reserved.
        </div>
    </div>
</footer>

<script>
// ── Mobile Nav Toggle ──
document.querySelector('.nav-toggle')?.addEventListener('click', function() {
    document.querySelector('.main-nav').classList.toggle('active');
});

// ── Dark Mode ──
(function() {
    var toggle = document.querySelector('.dark-toggle');
    if (!toggle) return;

    function getEffectiveTheme() {
        var saved = localStorage.getItem('moneydive-theme');
        if (saved) return saved;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('moneydive-theme', theme);
    }

    toggle.addEventListener('click', function() {
        var current = getEffectiveTheme();
        applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    // 시스템 설정 변경 감지
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        if (!localStorage.getItem('moneydive-theme')) {
            // 사용자가 수동 설정 안 했으면 시스템 따라감
        }
    });
})();

// ── TOC (Table of Contents) ──
(function() {
    var content = document.querySelector('.post-content');
    var toc = document.getElementById('toc');
    if (!content || !toc) return;

    var headings = content.querySelectorAll('h2');
    if (headings.length < 3) return;

    var list = toc.querySelector('.toc-list');
    headings.forEach(function(h, i) {
        var id = 'toc-' + i;
        h.setAttribute('id', id);

        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = '#' + id;
        a.textContent = h.textContent;
        li.appendChild(a);
        list.appendChild(li);
    });

    toc.classList.add('visible');

    // 접기/펼치기
    var header = toc.querySelector('.toc-header');
    var toggleBtn = toc.querySelector('.toc-toggle');
    header.addEventListener('click', function() {
        list.classList.toggle('collapsed');
        toggleBtn.textContent = list.classList.contains('collapsed') ? '펼치기' : '접기';
    });

    // 스크롤 하이라이트
    var tocLinks = list.querySelectorAll('a');
    var observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                tocLinks.forEach(function(l) { l.classList.remove('active'); });
                var active = list.querySelector('a[href="#' + entry.target.id + '"]');
                if (active) active.classList.add('active');
            }
        });
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0 });

    headings.forEach(function(h) { observer.observe(h); });
})();

// ── Prefetch on Hover ──
(function() {
    if ('ontouchstart' in window) return; // 모바일 제외

    var prefetched = {};
    var timer = null;

    document.addEventListener('mouseover', function(e) {
        var link = e.target.closest('a');
        if (!link) return;

        var href = link.href;
        if (!href || href.startsWith('#') || href.startsWith('javascript')) return;
        if (prefetched[href]) return;

        try {
            var url = new URL(href);
            if (url.origin !== window.location.origin) return;
        } catch(e) { return; }

        clearTimeout(timer);
        timer = setTimeout(function() {
            prefetched[href] = true;
            var el = document.createElement('link');
            el.rel = 'prefetch';
            el.href = href;
            document.head.appendChild(el);
        }, 200);
    });

    document.addEventListener('mouseout', function() {
        clearTimeout(timer);
    });
})();
</script>

<?php wp_footer(); ?>
</body>
</html>
