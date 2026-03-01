<!-- Newsletter Subscribe (준비되면 주석 해제) -->
<?php /*
<section class="newsletter-section">
    <div class="newsletter-inner">
        <div class="newsletter-text">
            <strong class="newsletter-title">매일 아침, 시장 브리핑을 받아보세요</strong>
            <p class="newsletter-desc">AI가 분석한 미국주식, 국내주식, 부동산 뉴스를 이메일로 전달해드려요.</p>
        </div>
        <form class="newsletter-form" id="newsletterForm">
            <input type="email" name="email" placeholder="이메일 주소" required class="newsletter-input" />
            <button type="submit" class="newsletter-btn">구독하기</button>
        </form>
        <p class="newsletter-msg" id="newsletterMsg"></p>
    </div>
</section>
*/ ?>

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

// ── Search Overlay ──
(function() {
    var overlay = document.getElementById('searchOverlay');
    if (!overlay) return;
    var input = overlay.querySelector('.search-input');
    document.querySelector('.search-toggle')?.addEventListener('click', function() {
        overlay.classList.add('active');
        setTimeout(function() { input.focus(); }, 100);
    });
    overlay.querySelector('.search-close')?.addEventListener('click', function() {
        overlay.classList.remove('active');
    });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.classList.remove('active');
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') overlay.classList.remove('active');
    });
})();

// ── Newsletter Subscribe ──
(function() {
    var form = document.getElementById('newsletterForm');
    var msg = document.getElementById('newsletterMsg');
    if (!form) return;
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        var email = form.querySelector('input[name="email"]').value;
        var btn = form.querySelector('button');
        btn.disabled = true;
        btn.textContent = '처리 중...';
        fetch('/wp-json/moneydive/v1/subscribe', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: email})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            msg.textContent = data.message;
            msg.className = 'newsletter-msg ' + (data.success ? 'success' : 'error');
            if (data.success) form.reset();
        })
        .catch(function() {
            msg.textContent = '오류가 발생했습니다. 다시 시도해주세요.';
            msg.className = 'newsletter-msg error';
        })
        .finally(function() {
            btn.disabled = false;
            btn.textContent = '구독하기';
        });
    });
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
