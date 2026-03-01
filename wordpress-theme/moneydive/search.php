<?php get_header(); ?>

<main class="site-content wide">

    <header class="search-header">
        <h1 class="search-title">
            <span class="search-keyword"><?php echo esc_html(get_search_query()); ?></span> 검색 결과
        </h1>
        <p class="search-count">
            <?php if (have_posts()) : ?>
                <?php printf('%d개의 글을 찾았습니다.', $wp_query->found_posts); ?>
            <?php else : ?>
                검색 결과가 없습니다.
            <?php endif; ?>
        </p>
    </header>

    <?php if (have_posts()) : ?>
    <div class="post-feed" style="border-top:1px solid var(--color-border);">
        <?php while (have_posts()) : the_post(); ?>
            <?php
            $cats = get_the_category();
            $cat_name = $cats ? $cats[0]->name : '';
            $cat_class = moneydive_category_class();
            $cat_slug = $cats ? $cats[0]->slug : '';
            $is_deep = ($cat_slug === 'deep-dive');
            ?>
            <a href="<?php the_permalink(); ?>" class="feed-row <?php if ($is_deep) echo 'feed-row-deep'; ?>">
                <div class="feed-row-main">
                    <span class="feed-row-title">
                        <?php if ($is_deep) : ?><span class="feed-deep-tag">DEEP</span><?php endif; ?>
                        <?php the_title(); ?>
                    </span>
                    <span class="feed-row-excerpt"><?php echo wp_trim_words(get_the_excerpt(), 20, '…'); ?></span>
                </div>
                <div class="feed-row-right">
                    <span class="feed-row-cat <?php echo esc_attr($cat_class); ?>"><?php echo esc_html($cat_name); ?></span>
                    <span class="feed-row-date"><?php echo get_the_date('n.j'); ?></span>
                </div>
            </a>
        <?php endwhile; ?>
    </div>

    <?php the_posts_pagination([
        'mid_size' => 2,
        'prev_text' => '&larr;',
        'next_text' => '&rarr;',
    ]); ?>

    <?php else : ?>
    <div class="search-empty">
        <p>다른 키워드로 검색해보세요.</p>
        <form role="search" method="get" action="<?php echo esc_url(home_url('/')); ?>" class="search-retry-form">
            <input type="search" name="s" value="<?php echo esc_attr(get_search_query()); ?>" class="newsletter-input" style="max-width:320px;" />
            <button type="submit" class="newsletter-btn">검색</button>
        </form>
    </div>
    <?php endif; ?>

</main>

<?php get_footer(); ?>
