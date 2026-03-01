<?php
/**
 * MoneyDive 테마 기능 설정
 */

// 테마 기본 설정
function moneydive_setup() {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('html5', ['search-form', 'comment-form', 'comment-list', 'gallery', 'caption']);
    add_theme_support('automatic-feed-links');

    register_nav_menus([
        'primary' => '메인 메뉴',
    ]);

    add_image_size('moneydive-hero', 1080, 608, true);
    add_image_size('moneydive-thumb', 400, 225, true);
    add_image_size('moneydive-small', 112, 112, true);
}
add_action('after_setup_theme', 'moneydive_setup');

// 스타일 로드
function moneydive_styles() {
    wp_enqueue_style('moneydive-style', get_stylesheet_uri(), [], '3.0.0');
}
add_action('wp_enqueue_scripts', 'moneydive_styles');

// Kakao SDK (single 페이지에서만)
// Kakao SDK
define('MONEYDIVE_KAKAO_JS_KEY', 'fe26d2c304495168a8d96e0a0b581d03');

function moneydive_kakao_sdk() {
    if (!is_singular('post')) {
        return;
    }
    if (empty(MONEYDIVE_KAKAO_JS_KEY)) {
        return;
    }
    wp_enqueue_script(
        'kakao-sdk',
        'https://t1.kakaocdn.net/kakao_js_sdk/2.7.4/kakao.min.js',
        [],
        null,
        true
    );
    wp_add_inline_script(
        'kakao-sdk',
        'Kakao.init("' . esc_js(MONEYDIVE_KAKAO_JS_KEY) . '");'
    );
}
add_action('wp_enqueue_scripts', 'moneydive_kakao_sdk');

// 발췌문 길이
function moneydive_excerpt_length($length) {
    return 40;
}
add_filter('excerpt_length', 'moneydive_excerpt_length');

// 발췌문 끝 표시
function moneydive_excerpt_more($more) {
    return '&hellip;';
}
add_filter('excerpt_more', 'moneydive_excerpt_more');

// 읽기 예상 시간 (한글 기준 분당 500자)
function moneydive_reading_time($post_id = null) {
    $post_id = $post_id ?: get_the_ID();
    $content = get_post_field('post_content', $post_id);
    $text = wp_strip_all_tags($content);
    $char_count = mb_strlen($text, 'UTF-8');
    $minutes = max(1, ceil($char_count / 500));
    return $minutes . '분 읽기';
}

// 카테고리 CSS 클래스 반환
function moneydive_category_class($post_id = null) {
    $post_id = $post_id ?: get_the_ID();
    $categories = get_the_category($post_id);
    if (empty($categories)) {
        return '';
    }
    $slug = $categories[0]->slug;
    $map = [
        'us-stocks'   => 'cat-us-stocks',
        'kr-stocks'   => 'cat-kr-stocks',
        'real-estate' => 'cat-real-estate',
        'daily-news'  => 'cat-daily-news',
        'deep-dive'   => 'cat-deep-dive',
    ];
    return isset($map[$slug]) ? $map[$slug] : '';
}

// ── SEO: OG 메타태그 + Twitter Card + meta description ──
function moneydive_og_meta() {
    $site_name = get_bloginfo('name');
    $default_og = get_template_directory_uri() . '/default-og.png';
    $has_default_og = file_exists(get_template_directory() . '/default-og.png');

    if (is_singular('post')) {
        $title = get_the_title();
        $url = get_permalink();
        $excerpt = get_the_excerpt();
        $description = $excerpt ?: wp_trim_words(wp_strip_all_tags(get_the_content()), 30, '…');

        $image = '';
        if (has_post_thumbnail()) {
            $image = get_the_post_thumbnail_url(null, 'full');
        } elseif ($has_default_og) {
            $image = $default_og;
        }

        echo '<meta property="og:type" content="article" />' . "\n";
        echo '<meta property="og:title" content="' . esc_attr($title) . '" />' . "\n";
        echo '<meta property="og:description" content="' . esc_attr($description) . '" />' . "\n";
        echo '<meta property="og:url" content="' . esc_url($url) . '" />' . "\n";
        echo '<meta property="og:site_name" content="' . esc_attr($site_name) . '" />' . "\n";
        echo '<meta property="og:locale" content="ko_KR" />' . "\n";
        echo '<meta property="article:published_time" content="' . esc_attr(get_the_date('c')) . '" />' . "\n";
        echo '<meta property="article:modified_time" content="' . esc_attr(get_the_modified_date('c')) . '" />' . "\n";
        $cats = get_the_category();
        if ($cats) {
            echo '<meta property="article:section" content="' . esc_attr($cats[0]->name) . '" />' . "\n";
        }
        if ($image) {
            echo '<meta property="og:image" content="' . esc_url($image) . '" />' . "\n";
            echo '<meta property="og:image:width" content="1200" />' . "\n";
            echo '<meta property="og:image:height" content="630" />' . "\n";
        }

        echo '<meta name="twitter:card" content="' . ($image ? 'summary_large_image' : 'summary') . '" />' . "\n";
        echo '<meta name="twitter:title" content="' . esc_attr($title) . '" />' . "\n";
        echo '<meta name="twitter:description" content="' . esc_attr($description) . '" />' . "\n";
        if ($image) {
            echo '<meta name="twitter:image" content="' . esc_url($image) . '" />' . "\n";
        }

        echo '<meta name="description" content="' . esc_attr($description) . '" />' . "\n";

    } elseif (is_category()) {
        $cat = get_queried_object();
        $desc = category_description($cat) ?: $cat->name . ' 관련 최신 브리핑 - ' . $site_name;
        echo '<meta property="og:type" content="website" />' . "\n";
        echo '<meta property="og:title" content="' . esc_attr($cat->name . ' - ' . $site_name) . '" />' . "\n";
        echo '<meta property="og:description" content="' . esc_attr(wp_strip_all_tags($desc)) . '" />' . "\n";
        echo '<meta property="og:url" content="' . esc_url(get_category_link($cat)) . '" />' . "\n";
        echo '<meta property="og:site_name" content="' . esc_attr($site_name) . '" />' . "\n";
        echo '<meta property="og:locale" content="ko_KR" />' . "\n";
        if ($has_default_og) {
            echo '<meta property="og:image" content="' . esc_url($default_og) . '" />' . "\n";
        }
        echo '<meta name="description" content="' . esc_attr(wp_strip_all_tags($desc)) . '" />' . "\n";

    } else {
        $desc = get_bloginfo('description');
        echo '<meta property="og:type" content="website" />' . "\n";
        echo '<meta property="og:title" content="' . esc_attr($site_name) . '" />' . "\n";
        echo '<meta property="og:description" content="' . esc_attr($desc) . '" />' . "\n";
        echo '<meta property="og:url" content="' . esc_url(home_url('/')) . '" />' . "\n";
        echo '<meta property="og:site_name" content="' . esc_attr($site_name) . '" />' . "\n";
        echo '<meta property="og:locale" content="ko_KR" />' . "\n";
        if ($has_default_og) {
            echo '<meta property="og:image" content="' . esc_url($default_og) . '" />' . "\n";
        }
        echo '<meta name="description" content="' . esc_attr($desc) . '" />' . "\n";
    }
}
add_action('wp_head', 'moneydive_og_meta', 1);

// ── SEO: Canonical URL ──
function moneydive_canonical() {
    if (is_singular()) {
        $url = get_permalink();
    } elseif (is_category()) {
        $url = get_category_link(get_queried_object_id());
    } elseif (is_home() || is_front_page()) {
        $url = home_url('/');
    } else {
        return;
    }
    echo '<link rel="canonical" href="' . esc_url($url) . '" />' . "\n";
}
add_action('wp_head', 'moneydive_canonical', 1);

// ── SEO: Robots 메타 ──
function moneydive_robots_meta() {
    if (is_search()) {
        echo '<meta name="robots" content="noindex, follow" />' . "\n";
    } elseif (is_paged() && (is_archive() || is_home())) {
        echo '<meta name="robots" content="noindex, follow" />' . "\n";
    } else {
        echo '<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1" />' . "\n";
    }
}
add_action('wp_head', 'moneydive_robots_meta', 1);

// ── SEO: JSON-LD 구조화 데이터 ──
function moneydive_json_ld() {
    $site_name = get_bloginfo('name');

    if (is_singular('post')) {
        $description = get_the_excerpt() ?: wp_trim_words(wp_strip_all_tags(get_the_content()), 30, '…');

        // Article 스키마
        $article = [
            '@context'         => 'https://schema.org',
            '@type'            => 'Article',
            'headline'         => get_the_title(),
            'description'      => $description,
            'url'              => get_permalink(),
            'datePublished'    => get_the_date('c'),
            'dateModified'     => get_the_modified_date('c'),
            'mainEntityOfPage' => [
                '@type' => 'WebPage',
                '@id'   => get_permalink(),
            ],
            'author'           => [
                '@type' => 'Organization',
                'name'  => $site_name,
            ],
            'publisher'        => [
                '@type' => 'Organization',
                'name'  => $site_name,
                'logo'  => [
                    '@type' => 'ImageObject',
                    'url'   => get_template_directory_uri() . '/favicon.svg',
                ],
            ],
        ];

        if (has_post_thumbnail()) {
            $article['image'] = [
                '@type' => 'ImageObject',
                'url'   => get_the_post_thumbnail_url(null, 'full'),
            ];
        }

        echo '<script type="application/ld+json">' . wp_json_encode($article, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . '</script>' . "\n";

        // BreadcrumbList 스키마
        $breadcrumb = [
            '@context'        => 'https://schema.org',
            '@type'           => 'BreadcrumbList',
            'itemListElement' => [
                [
                    '@type'    => 'ListItem',
                    'position' => 1,
                    'name'     => '홈',
                    'item'     => home_url('/'),
                ],
            ],
        ];

        $cats = get_the_category();
        if ($cats) {
            $breadcrumb['itemListElement'][] = [
                '@type'    => 'ListItem',
                'position' => 2,
                'name'     => $cats[0]->name,
                'item'     => get_category_link($cats[0]->term_id),
            ];
            $breadcrumb['itemListElement'][] = [
                '@type'    => 'ListItem',
                'position' => 3,
                'name'     => get_the_title(),
                'item'     => get_permalink(),
            ];
        } else {
            $breadcrumb['itemListElement'][] = [
                '@type'    => 'ListItem',
                'position' => 2,
                'name'     => get_the_title(),
                'item'     => get_permalink(),
            ];
        }

        echo '<script type="application/ld+json">' . wp_json_encode($breadcrumb, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . '</script>' . "\n";

    } elseif (is_home() || is_front_page()) {
        $website = [
            '@context'        => 'https://schema.org',
            '@type'           => 'WebSite',
            'name'            => $site_name,
            'description'     => get_bloginfo('description'),
            'url'             => home_url('/'),
            'inLanguage'      => 'ko-KR',
            'publisher'       => [
                '@type' => 'Organization',
                'name'  => $site_name,
            ],
            'potentialAction' => [
                '@type'       => 'SearchAction',
                'target'      => home_url('/?s={search_term_string}'),
                'query-input' => 'required name=search_term_string',
            ],
        ];

        echo '<script type="application/ld+json">' . wp_json_encode($website, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . '</script>' . "\n";
    }
}
add_action('wp_head', 'moneydive_json_ld', 2);

// ── SEO: 카테고리 아카이브 제목에서 접두사 제거 ──
function moneydive_archive_title($title) {
    if (is_category()) {
        return single_cat_title('', false);
    }
    if (is_tag()) {
        return single_tag_title('', false);
    }
    return $title;
}
add_filter('get_the_archive_title', 'moneydive_archive_title');

// 카테고리별 최근 글 가져오기
function moneydive_get_category_posts($slug, $count = 3) {
    return new WP_Query([
        'category_name' => $slug,
        'posts_per_page' => $count,
        'no_found_rows' => true,
    ]);
}

// 카카오 앱키가 설정되어 있는지 확인
function moneydive_has_kakao() {
    return defined('MONEYDIVE_KAKAO_JS_KEY') && !empty(MONEYDIVE_KAKAO_JS_KEY);
}

// ── Google Analytics 4 ──
define('MONEYDIVE_GA4_ID', 'G-GKDHY8X0ZK');

function moneydive_ga4() {
    if (empty(MONEYDIVE_GA4_ID)) return;
    ?>
    <script async src="https://www.googletagmanager.com/gtag/js?id=<?php echo esc_attr(MONEYDIVE_GA4_ID); ?>"></script>
    <script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','<?php echo esc_js(MONEYDIVE_GA4_ID); ?>');</script>
    <?php
}
add_action('wp_head', 'moneydive_ga4', 0);

// ── 필수 페이지 자동 생성 (개인정보처리방침, About) ──
function moneydive_create_required_pages() {
    $pages = [
        'privacy-policy' => [
            'title' => '개인정보처리방침',
            'file'  => 'privacy-policy-content.html',
        ],
        'about' => [
            'title' => '사이트 소개',
            'file'  => 'about-content.html',
        ],
    ];

    foreach ($pages as $slug => $page) {
        $content_file = get_template_directory() . '/' . $page['file'];
        if (!file_exists($content_file)) {
            continue;
        }
        $content = file_get_contents($content_file);

        $existing = get_page_by_path($slug);
        if ($existing) {
            // 임시글/휴지통이면 콘텐츠 덮어쓰고 발행
            if ($existing->post_status !== 'publish') {
                wp_update_post([
                    'ID'           => $existing->ID,
                    'post_title'   => $page['title'],
                    'post_content' => $content,
                    'post_status'  => 'publish',
                ]);
            }
            continue;
        }

        wp_insert_post([
            'post_title'   => $page['title'],
            'post_name'    => $slug,
            'post_content' => $content,
            'post_status'  => 'publish',
            'post_type'    => 'page',
        ]);
    }
}
add_action('init', 'moneydive_create_required_pages');

// ── 뉴스레터 구독 REST API ──
function moneydive_register_subscribe_endpoint() {
    register_rest_route('moneydive/v1', '/subscribe', [
        'methods'  => 'POST',
        'callback' => 'moneydive_handle_subscribe',
        'permission_callback' => '__return_true',
    ]);
}
add_action('rest_api_init', 'moneydive_register_subscribe_endpoint');

function moneydive_handle_subscribe($request) {
    $email = sanitize_email($request->get_param('email'));
    if (!is_email($email)) {
        return new WP_REST_Response(['success' => false, 'message' => '올바른 이메일을 입력해주세요.'], 400);
    }
    // subscribers 옵션에 저장
    $subscribers = get_option('moneydive_subscribers', []);
    if (in_array($email, $subscribers)) {
        return new WP_REST_Response(['success' => true, 'message' => '이미 구독 중입니다.'], 200);
    }
    $subscribers[] = $email;
    update_option('moneydive_subscribers', $subscribers);
    return new WP_REST_Response(['success' => true, 'message' => '구독해주셔서 감사합니다!'], 200);
}

// ── Core Web Vitals: 리소스 힌트 ──
function moneydive_resource_hints() {
    // DNS prefetch & preconnect
    echo '<link rel="preconnect" href="https://www.googletagmanager.com" crossorigin />' . "\n";
    echo '<link rel="dns-prefetch" href="https://www.googletagmanager.com" />' . "\n";
    echo '<link rel="dns-prefetch" href="https://pagead2.googlesyndication.com" />' . "\n";
}
add_action('wp_head', 'moneydive_resource_hints', 0);

// ── Core Web Vitals: 이미지 lazy loading ──
function moneydive_lazy_load_images($content) {
    if (is_admin()) return $content;
    return preg_replace('/<img((?!loading=)[^>]*)>/i', '<img$1 loading="lazy">', $content);
}
add_filter('the_content', 'moneydive_lazy_load_images', 99);

// ── Core Web Vitals: 불필요한 헤더 제거 ──
remove_action('wp_head', 'wp_generator');
remove_action('wp_head', 'wlwmanifest_link');
remove_action('wp_head', 'rsd_link');
remove_action('wp_head', 'wp_shortlink_wp_head');
remove_action('wp_head', 'rest_output_link_wp_head');
remove_action('wp_head', 'wp_oembed_add_discovery_links');
add_filter('emoji_svg_url', '__return_false');

function moneydive_disable_emojis() {
    remove_action('wp_head', 'print_emoji_detection_script', 7);
    remove_action('wp_print_styles', 'print_emoji_styles');
}
add_action('init', 'moneydive_disable_emojis');
