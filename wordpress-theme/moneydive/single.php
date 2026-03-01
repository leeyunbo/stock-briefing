<?php get_header(); ?>

<div class="reading-progress-bar" id="readingProgress"></div>

<main class="site-content">

<?php if (have_posts()) : the_post(); ?>

    <article>
        <!-- Breadcrumb -->
        <nav class="breadcrumb" aria-label="breadcrumb">
            <a href="<?php echo esc_url(home_url('/')); ?>">홈</a>
            <span class="breadcrumb-sep">&rsaquo;</span>
            <?php
            $categories = get_the_category();
            $cat_class = moneydive_category_class();
            if ($categories) :
            ?>
                <a href="<?php echo esc_url(get_category_link($categories[0]->term_id)); ?>"><?php echo esc_html($categories[0]->name); ?></a>
                <span class="breadcrumb-sep">&rsaquo;</span>
            <?php endif; ?>
            <span class="breadcrumb-current"><?php echo wp_trim_words(get_the_title(), 6, '…'); ?></span>
        </nav>

        <header class="single-header">
            <?php if ($categories) : ?>
                <a href="<?php echo esc_url(get_category_link($categories[0]->term_id)); ?>" class="post-category <?php echo esc_attr($cat_class); ?>">
                    <?php echo esc_html($categories[0]->name); ?>
                </a>
            <?php endif; ?>

            <h1 class="post-title"><?php the_title(); ?></h1>

            <div class="post-meta">
                <time datetime="<?php echo get_the_date('c'); ?>"><?php echo get_the_date(); ?></time>
                <span class="sep">&middot;</span>
                <span class="reading-time"><?php echo moneydive_reading_time(); ?></span>
            </div>
        </header>

        <nav id="toc">
            <div class="toc-header">
                <span class="toc-title">목차</span>
                <button class="toc-toggle" aria-label="목차 접기/펼치기">접기</button>
            </div>
            <ol class="toc-list"></ol>
        </nav>

        <div class="post-content">
            <?php the_content(); ?>
        </div>

        <!-- Social Share -->
        <div class="share-bar">
            <div class="share-label">공유하기</div>
            <div class="share-buttons">
                <button class="share-btn kakao" onclick="moneydiveShareKakao()">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.477 3 2 6.463 2 10.691c0 2.722 1.8 5.108 4.509 6.457-.199.744-.72 2.696-.826 3.113-.13.516.189.509.398.37.164-.109 2.61-1.774 3.67-2.494.731.104 1.484.159 2.249.159 5.523 0 10-3.463 10-7.605C22 6.463 17.523 3 12 3z"/></svg>
                    <span>카카오톡</span>
                </button>
                <button class="share-btn twitter" onclick="moneydiveShareX()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                    <span>X</span>
                </button>
                <button class="share-btn copy-link" onclick="moneydiveCopyLink(this)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                    <span>링크 복사</span>
                </button>
            </div>
        </div>
    </article>

    <!-- Related Posts -->
    <?php
    $related_cats = get_the_category();
    if ($related_cats) :
        $related = new WP_Query([
            'category__in'   => [$related_cats[0]->term_id],
            'post__not_in'   => [get_the_ID()],
            'posts_per_page' => 3,
            'no_found_rows'  => true,
        ]);
        if ($related->have_posts()) :
    ?>
    <section class="related-posts">
        <h2 class="section-title">관련 글</h2>
        <div class="related-grid">
            <?php while ($related->have_posts()) : $related->the_post(); ?>
            <a href="<?php the_permalink(); ?>" class="related-card">
                <div class="related-thumb">
                    <?php if (has_post_thumbnail()) : ?>
                        <?php the_post_thumbnail('moneydive-thumb'); ?>
                    <?php else : ?>
                        <div class="no-thumb">&#x1f4c4;</div>
                    <?php endif; ?>
                </div>
                <div class="related-info">
                    <div class="related-title"><?php the_title(); ?></div>
                    <div class="related-date"><?php echo get_the_date(); ?></div>
                </div>
            </a>
            <?php endwhile; ?>
        </div>
    </section>
    <?php
        endif;
        wp_reset_postdata();
    endif;
    ?>

    <!-- Post Navigation -->
    <nav class="post-nav">
        <?php
        $prev = get_previous_post();
        $next = get_next_post();
        ?>
        <div class="post-nav-item prev">
            <?php if ($prev) : ?>
                <div class="nav-label">&larr; 이전 글</div>
                <a href="<?php echo get_permalink($prev); ?>"><?php echo get_the_title($prev); ?></a>
            <?php endif; ?>
        </div>
        <div class="post-nav-item next">
            <?php if ($next) : ?>
                <div class="nav-label">다음 글 &rarr;</div>
                <a href="<?php echo get_permalink($next); ?>"><?php echo get_the_title($next); ?></a>
            <?php endif; ?>
        </div>
    </nav>

<?php endif; ?>

</main>

<script>
// Kakao share
function moneydiveShareKakao() {
    if (typeof Kakao !== 'undefined' && Kakao.isInitialized()) {
        Kakao.Share.sendDefault({
            objectType: 'feed',
            content: {
                title: <?php echo json_encode(get_the_title()); ?>,
                description: <?php echo json_encode(wp_trim_words(wp_strip_all_tags(get_the_content()), 20, '…')); ?>,
                imageUrl: <?php echo json_encode(get_the_post_thumbnail_url(null, 'full') ?: ''); ?>,
                link: {
                    mobileWebUrl: <?php echo json_encode(get_permalink()); ?>,
                    webUrl: <?php echo json_encode(get_permalink()); ?>
                }
            }
        });
    } else {
        // Kakao SDK 미설정 시 모바일 카카오톡 공유 URL 폴백
        var shareUrl = 'https://sharer.kakao.com/talk/friends/picker/link?url=' + encodeURIComponent(window.location.href);
        window.open(shareUrl, '_blank', 'width=600,height=400');
    }
}

// X (Twitter) share
function moneydiveShareX() {
    var text = encodeURIComponent(document.title);
    var url = encodeURIComponent(window.location.href);
    window.open('https://twitter.com/intent/tweet?text=' + text + '&url=' + url, '_blank', 'width=600,height=400');
}

// Reading progress bar
(function() {
    var bar = document.getElementById('readingProgress');
    var content = document.querySelector('.post-content');
    if (!bar || !content) return;
    var ticking = false;
    window.addEventListener('scroll', function() {
        if (!ticking) {
            requestAnimationFrame(function() {
                var rect = content.getBoundingClientRect();
                var scrollable = content.offsetHeight - window.innerHeight;
                if (scrollable <= 0) { bar.style.width = '100%'; ticking = false; return; }
                var scrolled = -rect.top;
                var pct = Math.min(100, Math.max(0, (scrolled / scrollable) * 100));
                bar.style.width = pct + '%';
                ticking = false;
            });
            ticking = true;
        }
    });
})();

// Copy link
function moneydiveCopyLink(btn) {
    navigator.clipboard.writeText(window.location.href).then(function() {
        var span = btn.querySelector('span');
        span.textContent = '복사됨!';
        btn.classList.add('copied');
        setTimeout(function() {
            span.textContent = '링크 복사';
            btn.classList.remove('copied');
        }, 2000);
    });
}
</script>

<?php get_footer(); ?>
