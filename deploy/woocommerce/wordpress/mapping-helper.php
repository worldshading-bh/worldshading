<?php
/** Read-only ERPNext product identifiers for store managers. */
defined( 'ABSPATH' ) || exit;

class WSC_ERP_Product_Mapping {
    public static function register() {
        add_action( 'admin_bar_menu', array( __CLASS__, 'toolbar' ), 81 );
        add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
        add_action( 'add_meta_boxes_product', array( __CLASS__, 'metabox' ) );
        add_action( 'wp_footer', array( __CLASS__, 'popup_script' ), 100 );
        add_action( 'admin_footer', array( __CLASS__, 'popup_script' ), 100 );
    }

    private static function allowed( $id ) {
        return $id && current_user_can( 'manage_woocommerce' ) && current_user_can( 'edit_post', $id );
    }

    private static function url( $id, $page = 1 ) {
        return add_query_arg( array( 'page' => 'wsc-erp-mapping', 'product_id' => $id, 'mapping_page' => $page ), admin_url( 'admin.php' ) );
    }

    private static function erp_url( $id, $variation_id = null ) {
        // Public ERP origin only; authentication stays in the user's ERP session.
        $origin = defined( 'WSC_ERP_MAPPING_ORIGIN' ) ? WSC_ERP_MAPPING_ORIGIN : 'https://erp.worldshading.com';
        $parts = wp_parse_url( $origin );
        if ( ! is_array( $parts ) || ( $parts['scheme'] ?? '' ) !== 'https' || empty( $parts['host'] ) ||
            isset( $parts['user'] ) || isset( $parts['pass'] ) || isset( $parts['port'] ) || isset( $parts['query'] ) || isset( $parts['fragment'] ) ||
            ! in_array( $parts['path'] ?? '', array( '', '/' ), true ) ) {
            return self::url( $id );
        }
        return rtrim( $origin, '/' ) . '/desk#ws-woocommerce-link/' . absint( $id ) .
            '/' . ( null === $variation_id ? 'all' : absint( $variation_id ) ) . '/' . rawurlencode( (string) wp_parse_url( home_url( '/' ), PHP_URL_HOST ) );
    }

    public static function popup_script() {
        if ( ! current_user_can( 'manage_woocommerce' ) ) { return; }
        if ( is_admin() ) {
            $screen = get_current_screen();
            $mapping_page = isset( $_GET['page'] ) && 'wsc-erp-mapping' === $_GET['page'];
            $id = $mapping_page ? self::number( 'product_id' ) : ( $screen && 'post' === $screen->base && 'product' === $screen->post_type ? get_the_ID() : 0 );
        } else {
            $id = function_exists( 'is_product' ) && is_product() ? get_queried_object_id() : 0;
        }
        if ( ! self::allowed( $id ) ) { return; }
        ?>
        <script>
        (function () {
            document.addEventListener('click', function (event) {
                var link = event.target.closest('#wp-admin-bar-wsc-erp-mapping > a, a.wsc-erp-popup');
                if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
                var popup = window.open('about:blank', '_blank', 'popup=yes,width=1060,height=820');
                if (!popup) return; // Normal link still works when popups are blocked.
                popup.opener = null;
                popup.location.href = link.href;
                event.preventDefault();
            });
        }());
        </script>
        <?php
    }

    public static function toolbar( $bar ) {
        if ( ! function_exists( 'wc_get_product' ) || ! is_admin_bar_showing() ) { return; }
        if ( is_admin() ) {
            $screen = get_current_screen();
            $id = $screen && 'post' === $screen->base && 'product' === $screen->post_type ? get_the_ID() : 0;
        } else {
            $id = function_exists( 'is_product' ) && is_product() ? get_queried_object_id() : 0;
        }
        if ( ! self::allowed( $id ) ) { return; }
        $bar->add_node( array( 'id' => 'wsc-erp-mapping', 'title' => 'ERPNext Mapping', 'href' => self::erp_url( $id ),
            'meta' => array( 'target' => '_blank', 'rel' => 'noopener', 'title' => 'Link this product to an ERPNext Item' ) ) );
    }

    public static function menu() {
        add_submenu_page( null, 'ERPNext Mapping', 'ERPNext Mapping', 'manage_woocommerce', 'wsc-erp-mapping', array( __CLASS__, 'page' ) );
    }

    public static function metabox( $post ) {
        if ( ! self::allowed( $post->ID ) ) { return; }
        add_meta_box( 'wsc-erp-mapping', 'ERPNext Mapping', array( __CLASS__, 'box' ), 'product', 'side', 'default' );
    }

    public static function box( $post ) {
        if ( ! self::allowed( $post->ID ) ) { return; }
        echo '<p><a class="button wsc-erp-popup" target="_blank" rel="noopener" href="' . esc_url( self::erp_url( $post->ID ) ) . '">Link ERPNext Item</a></p>';
    }

    private static function cell( $value, $label ) {
        echo '<td><input class="wsc-erp-value" readonly size="14" aria-label="' . esc_attr( $label ) . '" value="' . esc_attr( $value ) . '"> ';
        echo '<button type="button" class="button wsc-erp-copy" aria-label="' . esc_attr( 'Copy ' . $label ) . '">Copy</button></td>';
    }

    private static function number( $key ) {
        return isset( $_GET[ $key ] ) && is_scalar( $_GET[ $key ] ) ? absint( wp_unslash( $_GET[ $key ] ) ) : 0;
    }

    public static function page() {
        $id = self::number( 'product_id' );
        if ( ! self::allowed( $id ) ) { wp_die( 'You cannot view mappings for this product.', '', array( 'response' => 403 ) ); }
        $product = function_exists( 'wc_get_product' ) ? wc_get_product( $id ) : false;
        if ( ! $product || ! $product->is_type( array( 'simple', 'variable' ) ) ) {
            wp_die( 'Choose an existing simple or variable product.', '', array( 'response' => 404 ) );
        }
        $children = $product->is_type( 'variable' ) ? $product->get_children() : array( $id );
        $pages = max( 1, (int) ceil( count( $children ) / 25 ) );
        $page = min( $pages, max( 1, self::number( 'mapping_page' ) ) );
        $ids = array_slice( $children, ( $page - 1 ) * 25, 25 );
        echo '<div class="wrap"><h1>ERPNext Mapping</h1><h2>' . esc_html( $product->get_name( 'edit' ) ) . '</h2>';
        echo '<p><a class="button button-primary wsc-erp-popup" target="_blank" rel="noopener" href="' . esc_url( self::erp_url( $id ) ) . '">Open Linking Popup</a></p>';
        echo '<p>Select an existing ERPNext Item and selling UOM in the popup. Your ERPNext login is required.</p>';
        echo '<p><a href="' . esc_url( add_query_arg( array( 'post' => $id, 'action' => 'edit' ), admin_url( 'post.php' ) ) ) . '">Edit product</a></p>';
        echo '<div style="overflow-x:auto"><table class="widefat striped" id="wsc-erp-mapping-table"><thead><tr>';
        foreach ( array( 'Product / Variation', 'Parent Product ID', 'Variation ID', 'SKU', 'ERPNext Item' ) as $title ) {
            echo '<th scope="col">' . esc_html( $title ) . '</th>';
        }
        echo '</tr></thead><tbody>';
        foreach ( $ids as $child_id ) {
            $row = $product->is_type( 'variable' ) ? wc_get_product( $child_id ) : $product;
            if ( ! $row || ( $product->is_type( 'variable' ) && (int) $row->get_parent_id() !== $id ) ) { continue; }
            echo '<tr><td>' . esc_html( wp_strip_all_tags( $row->get_name( 'edit' ) ) ) . '</td>';
            self::cell( $id, 'Parent Product ID' );
            self::cell( $product->is_type( 'variable' ) ? $row->get_id() : 0, 'Variation ID' );
            self::cell( $row->get_sku(), 'SKU' );
            echo '<td><a class="button wsc-erp-popup" target="_blank" rel="noopener" href="' . esc_url( self::erp_url( $id, $product->is_type( 'variable' ) ? $row->get_id() : 0 ) ) . '">Link Item</a></td>';
            echo '</tr>';
        }
        echo '</tbody></table></div>';
        if ( ! $children ) { echo '<p>No variations have been saved yet.</p>'; }
        if ( $pages > 1 ) {
            echo '<p>Page ' . esc_html( $page ) . ' of ' . esc_html( $pages ) . ' ';
            if ( $page > 1 ) { echo '<a class="button" href="' . esc_url( self::url( $id, $page - 1 ) ) . '">Previous</a> '; }
            if ( $page < $pages ) { echo '<a class="button" href="' . esc_url( self::url( $id, $page + 1 ) ) . '">Next</a>'; }
            echo '</p>';
        }
        echo '<p>For a simple product, Variation ID is 0. A blank SKU must be filled on the product or variation before linking.</p>';
        echo '<p id="wsc-erp-copy-status" role="status" aria-live="polite"></p></div>';
        ?>
        <script>
        (function () {
            var table = document.getElementById('wsc-erp-mapping-table');
            var status = document.getElementById('wsc-erp-copy-status');
            table.addEventListener('click', function (event) {
                var button = event.target.closest('.wsc-erp-copy');
                if (!button || !table.contains(button)) return;
                var input = button.parentElement.querySelector('input');
                function selectFallback() {
                    input.focus(); input.select();
                    status.textContent = 'Value selected. Press Ctrl+C or Command+C to copy.';
                }
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(input.value).then(function () {
                        status.textContent = input.getAttribute('aria-label') + ' copied: ' + input.value;
                    }, selectFallback);
                } else { selectFallback(); }
            });
        }());
        </script>
        <?php
    }
}
WSC_ERP_Product_Mapping::register();
