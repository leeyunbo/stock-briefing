<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <?php if (!is_singular('post')) : ?>
    <meta name="description" content="<?php bloginfo('description'); ?>">
    <?php endif; ?>
    <script>
    // FOUC 방지: 페이지 로드 전에 다크모드 적용
    (function() {
        var saved = localStorage.getItem('moneydive-theme');
        if (saved) {
            document.documentElement.setAttribute('data-theme', saved);
        }
    })();
    </script>
    <link rel="icon" href="<?php echo get_template_directory_uri(); ?>/favicon.svg" type="image/svg+xml">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4954162689241129" crossorigin="anonymous"></script>
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<header class="site-header">
    <div class="header-inner">
        <a href="<?php echo esc_url(home_url('/')); ?>" class="site-logo">
            머니<span>다이브</span>
        </a>

        <div class="header-right">
            <nav class="main-nav">
                <?php
                wp_nav_menu([
                    'theme_location' => 'primary',
                    'container' => false,
                    'fallback_cb' => 'moneydive_default_menu',
                ]);
                ?>
            </nav>

            <button class="dark-toggle" aria-label="다크모드 전환">
                <span class="icon-moon">&#x1f319;</span>
                <span class="icon-sun">&#x2600;&#xfe0f;</span>
            </button>

            <button class="nav-toggle" aria-label="메뉴 열기">&#9776;</button>
        </div>
    </div>
</header>

<?php
function moneydive_default_menu() {
    echo '<ul>';
    echo '<li><a href="' . esc_url(home_url('/')) . '">홈</a></li>';
    echo '<li><a href="' . esc_url(home_url('/category/us-stocks/')) . '">미국주식</a></li>';
    echo '<li><a href="' . esc_url(home_url('/category/kr-stocks/')) . '">국내주식</a></li>';
    echo '<li><a href="' . esc_url(home_url('/category/real-estate/')) . '">부동산</a></li>';
    echo '<li><a href="' . esc_url(home_url('/category/market/')) . '">시장</a></li>';
    echo '</ul>';
}
?>
