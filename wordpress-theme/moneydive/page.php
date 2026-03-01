<?php get_header(); ?>

<main class="site-content">

<?php if (have_posts()) : the_post(); ?>

    <article>
        <header class="single-header">
            <h1 class="post-title"><?php the_title(); ?></h1>
        </header>

        <div class="post-content">
            <?php the_content(); ?>
        </div>
    </article>

<?php endif; ?>

</main>

<?php get_footer(); ?>
