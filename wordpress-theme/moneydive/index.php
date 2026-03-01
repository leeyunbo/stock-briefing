<?php get_header(); ?>

<?php if (have_posts()) : ?>

    <?php the_post(); ?>
    <div class="main-card">

        <!-- Hero: 최신 글 -->
        <section class="hero-section">
            <div class="hero-body">
                <div class="hero-badge">
                    <span class="hero-badge-dot"></span>
                    <span class="hero-badge-text">최신 브리핑</span>
                </div>
                <h1 class="hero-title">
                    <a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
                </h1>
                <p class="hero-excerpt"><?php echo get_the_excerpt(); ?></p>
                <div class="hero-meta-row">
                    <?php
                    $cats = get_the_category();
                    $cat_class = moneydive_category_class();
                    if ($cats) :
                    ?>
                    <span class="hero-cat <?php echo esc_attr($cat_class); ?>"><?php echo esc_html($cats[0]->name); ?></span>
                    <span class="hero-sep">&middot;</span>
                    <?php endif; ?>
                    <span><?php echo get_the_date(); ?></span>
                    <span class="hero-sep">&middot;</span>
                    <span><?php echo moneydive_reading_time(); ?></span>
                </div>
            </div>
        </section>

        <?php
        $hero_id = get_the_ID();
        $recent = new WP_Query([
            'posts_per_page' => 20,
            'post__not_in' => [$hero_id],
            'no_found_rows' => false,
        ]);

        if ($recent->have_posts()) :
            $count = 0;
        ?>

        <!-- 카드 그리드: 상위 4개 -->
        <section class="card-grid">
            <?php while ($recent->have_posts() && $count < 4) : $recent->the_post(); $count++; ?>
                <?php
                $cats = get_the_category();
                $cat_name = $cats ? $cats[0]->name : '';
                $cat_class = moneydive_category_class();
                $cat_slug = $cats ? $cats[0]->slug : '';
                $is_deep = ($cat_slug === 'deep-dive');
                ?>
                <a href="<?php the_permalink(); ?>" class="card-item <?php echo esc_attr($cat_class); ?> <?php if ($is_deep) echo 'card-deep-dive'; ?>">
                    <?php if ($is_deep) : ?>
                        <span class="card-deep-label">DEEP DIVE</span>
                    <?php endif; ?>
                    <span class="card-cat"><?php echo esc_html($cat_name); ?></span>
                    <span class="card-title"><?php the_title(); ?></span>
                    <span class="card-excerpt"><?php echo wp_trim_words(get_the_excerpt(), 18, '…'); ?></span>
                    <span class="card-meta"><?php echo get_the_date('n.j'); ?> &middot; <?php echo moneydive_reading_time(); ?></span>
                </a>
            <?php endwhile; ?>
        </section>

        <!-- 리스트 피드: 나머지 -->
        <?php if ($recent->have_posts()) : ?>
        <section class="post-feed">
            <?php while ($recent->have_posts()) : $recent->the_post(); ?>
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
                        <span class="feed-row-excerpt"><?php echo wp_trim_words(get_the_excerpt(), 15, '…'); ?></span>
                    </div>
                    <div class="feed-row-right">
                        <span class="feed-row-cat <?php echo esc_attr($cat_class); ?>"><?php echo esc_html($cat_name); ?></span>
                        <span class="feed-row-time"><?php echo moneydive_reading_time(); ?></span>
                        <span class="feed-row-date"><?php echo get_the_date('n.j'); ?></span>
                    </div>
                </a>
            <?php endwhile; ?>
        </section>
        <?php endif; ?>

        <?php
            wp_reset_postdata();
        endif;
        ?>

        <?php
        $total_posts = wp_count_posts()->publish;
        if ($total_posts > 21) :
        ?>
        <div class="feed-more">
            <a href="<?php echo get_pagenum_link(2); ?>" class="feed-more-btn">이전 글 더보기</a>
        </div>
        <?php endif; ?>

    </div>

<?php else : ?>
    <main class="site-content">
        <p>아직 발행된 글이 없습니다.</p>
    </main>
<?php endif; ?>

<?php get_footer(); ?>
