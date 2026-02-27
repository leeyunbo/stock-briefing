<?php get_header(); ?>

<main class="site-content">

    <header class="single-header">
        <h1 class="post-title"><?php the_archive_title(); ?></h1>
    </header>

    <div class="post-list">
    <?php if (have_posts()) : ?>
        <?php while (have_posts()) : the_post(); ?>
            <article class="post-item">
                <?php
                $categories = get_the_category();
                $cat_class = moneydive_category_class();
                if ($categories) :
                ?>
                    <span class="post-category <?php echo esc_attr($cat_class); ?>"><?php echo esc_html($categories[0]->name); ?></span>
                <?php endif; ?>

                <h2 class="post-title">
                    <a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
                </h2>

                <p class="post-excerpt"><?php echo get_the_excerpt(); ?></p>

                <span class="post-meta">
                    <?php echo get_the_date(); ?>
                    <span class="sep">&middot;</span>
                    <span class="reading-time"><?php echo moneydive_reading_time(); ?></span>
                </span>
            </article>
        <?php endwhile; ?>

        <div class="pagination">
            <?php
            echo paginate_links([
                'prev_text' => '&laquo; 이전',
                'next_text' => '다음 &raquo;',
            ]);
            ?>
        </div>

    <?php else : ?>
        <p>글이 없습니다.</p>
    <?php endif; ?>
    </div>

</main>

<?php get_footer(); ?>
