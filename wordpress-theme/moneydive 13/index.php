<?php get_header(); ?>

<?php if (have_posts()) : ?>

    <?php the_post(); ?>
    <div class="main-card">

        <section class="hero-section">
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
                if ($cats) :
                ?>
                <span class="hero-cat"><?php echo esc_html($cats[0]->name); ?></span>
                <span class="hero-sep">&middot;</span>
                <?php endif; ?>
                <span><?php echo get_the_date(); ?></span>
                <span class="hero-sep">&middot;</span>
                <span><?php echo moneydive_reading_time(); ?></span>
            </div>
        </section>

        <section class="post-feed">
            <?php
            $recent = new WP_Query([
                'posts_per_page' => 20,
                'post__not_in' => [get_the_ID()],
                'no_found_rows' => false,
            ]);

            if ($recent->have_posts()) :
                while ($recent->have_posts()) : $recent->the_post();
                    $cats = get_the_category();
                    $cat_name = $cats ? $cats[0]->name : '';
                    $cat_class = moneydive_category_class();
            ?>
            <a href="<?php the_permalink(); ?>" class="feed-row">
                <div class="feed-row-main">
                    <span class="feed-row-title"><?php the_title(); ?></span>
                </div>
                <div class="feed-row-right">
                    <span class="feed-row-cat <?php echo esc_attr($cat_class); ?>"><?php echo esc_html($cat_name); ?></span>
                    <span class="feed-row-date"><?php echo get_the_date('n.j'); ?></span>
                </div>
            </a>
            <?php
                endwhile;
                wp_reset_postdata();
            endif;
            ?>
        </section>

        <?php
        $big_args = [
            'posts_per_page' => 1,
            'fields' => 'ids',
        ];
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
