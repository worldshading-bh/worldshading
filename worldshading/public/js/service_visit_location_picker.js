// apps/worldshading/worldshading/public/js/service_visit_location_picker.js
window.worldshading = window.worldshading || {};

worldshading.service_visit_location_picker = {
	init: function(opts) {
		var me = this;

		me.opts = $.extend({
			map_field: "map_html",
			latitude_field: "location_latitude",
			longitude_field: "location_longitude",
			address_field: "location_address",
			place_id_field: "google_place_id",
			maps_link_field: "google_maps_link",
			method_field: "location_method",
			require_location: true,
			flat_no_field: "flat_no",
			building_no_field: "building_no",
			road_no_field: "road_no",
			block_field: "block",
			city_field: "city",
			country_field: "country",
			directions_field: "visit_notes",
			default_lat: 26.0667,
			default_lng: 50.5577,
			default_zoom: 13
		}, opts || {});

		if (!me.opts.api_key) {
			me.show_message("Google Maps API key is missing.");
			return;
		}

		me.render();

		if (me.opts.require_location) {
			me.wrap_validation();
		}
		
		me.bind();
		me.bind_viewport_events();
		me.render_summary();
	},

	render: function() {
		var field = frappe.web_form.fields_dict[this.opts.map_field];
		var wrapper = field && (field.$wrapper || $(field.wrapper));

		if (!wrapper || !wrapper.length) {
			return;
		}

		wrapper.closest(".frappe-control").find(".control-label").hide();

		wrapper.html(
			'<div class="ws-site-address-box">' +
				'<div class="ws-address-summary"></div>' +
				'<button type="button" class="ws-choose-site-address">' +
					'<span class="ws-choose-site-icon"></span>' +
					'<span class="ws-choose-site-title">Choose Site Address</span>' +
				'</button>' +
				'<div class="ws-location-error"></div>' +
			'</div>' +
			'<div class="ws-location-overlay" style="display:none;">' +
				'<div class="ws-location-screen ws-map-screen">' +
					'<div class="ws-location-header">' +
						'<button type="button" class="ws-location-back" aria-label="Close"></button>' +
						'<div class="ws-location-heading">Confirm Location</div>' +
						'<button type="button" class="ws-location-search-toggle" aria-label="Search"></button>' +
					'</div>' +
					'<div class="ws-search-panel" style="display:none;">' +
						'<input type="text" class="ws-map-search" placeholder="Search area, landmark, business or address">' +
						'<button type="button" class="ws-clear-search" aria-label="Clear search"></button>' +
					'</div>' +
					'<div class="ws-map-stage">' +
						'<div class="ws-map-canvas"></div>' +
						'<div class="ws-center-callout">Service location here</div>' +
						'<div class="ws-center-pin"></div>' +
						'<button type="button" class="ws-current-location" aria-label="Use current location"></button>' +
					'</div>' +
					'<div class="ws-map-footer">' +
						'<div class="ws-map-status"></div>' +
						'<button type="button" class="ws-fill-address">Fill Complete Address</button>' +
					'</div>' +
				'</div>' +
				'<div class="ws-location-screen ws-address-screen" style="display:none;">' +
					'<div class="ws-location-header">' +
						'<button type="button" class="ws-address-back" aria-label="Back"></button>' +
						'<div class="ws-location-heading">Complete Address</div>' +
						'<span class="ws-location-header-space"></span>' +
					'</div>' +
					'<div class="ws-address-content">' +
						'<div class="ws-preview-map"></div>' +
						'<div class="ws-area-card">' +
							'<span class="ws-area-icon"></span>' +
							'<div><div class="ws-area-label">Area / City</div><input type="text" class="ws-address-input ws-city-input" placeholder="Area / City"></div>' +
							'<button type="button" class="ws-change-location">Change</button>' +
						'</div>' +
						'<div class="ws-address-type-row">' +
							'<button type="button" class="ws-address-type active" data-address-type="House">House</button>' +
							'<button type="button" class="ws-address-type" data-address-type="Apartment">Apartment</button>' +
						'</div>' +
						'<label class="ws-input-wrap"><span class="ws-input-label">Building No</span><input type="text" class="ws-address-input ws-building-input" placeholder="Building No"></label>' +
						'<label class="ws-input-wrap"><span class="ws-input-label">Flat / Home</span><input type="text" class="ws-address-input ws-flat-input" placeholder="Flat / Home"></label>' +
						'<label class="ws-input-wrap"><span class="ws-input-label">Road / Street No</span><input type="text" class="ws-address-input ws-road-input" placeholder="Road / Street No"></label>' +
						'<label class="ws-input-wrap"><span class="ws-input-label">Block</span><input type="text" class="ws-address-input ws-block-input" placeholder="Block"></label>' +
						'<label class="ws-input-wrap"><span class="ws-input-label">Additional Directions</span><textarea class="ws-address-input ws-directions-input" placeholder="Additional Directions" rows="3"></textarea></label>' +
						'<div class="ws-address-error" style="display:none;"></div>' +
					'</div>' +
					'<div class="ws-address-footer">' +
						'<button type="button" class="ws-confirm-address">Confirm Address</button>' +
					'</div>' +
				'</div>' +
			'</div>' +
			'<style>' +
				'.ws-site-address-box,.ws-site-address-box *,.ws-location-overlay,.ws-location-overlay *{box-sizing:border-box;}' +
				'.ws-site-address-box{margin:12px 0 18px 0;}' +
				'.ws-choose-site-address,.ws-fill-address,.ws-confirm-address{width:100%;border:0;border-radius:8px;background:#E54B2C;color:#fff;font-size:16px;font-weight:700;padding:15px 18px;line-height:1.2;transition:background .15s ease,box-shadow .15s ease,transform .15s ease;}' +
				'.ws-choose-site-address:focus,.ws-fill-address:focus,.ws-confirm-address:focus,.ws-location-back:focus,.ws-address-back:focus,.ws-location-search-toggle:focus,.ws-current-location:focus,.ws-change-location:focus,.ws-address-type:focus{outline:none;box-shadow:0 0 0 3px rgba(229,75,44,.22);}' +
				'.ws-choose-site-address:active,.ws-fill-address:active,.ws-confirm-address:active,.ws-current-location:active{transform:translateY(1px);}' +
				'.ws-fill-address:disabled,.ws-confirm-address:disabled{background:rgba(229,75,44,.55);color:#fff;cursor:wait;}' +
				'.ws-choose-site-address{display:flex;align-items:center;justify-content:center;gap:9px;background:#fff;color:#202124;text-align:center;border:1px solid #d8dde3;box-shadow:0 1px 3px rgba(16,24,40,.05);}' +
				'.ws-choose-site-address:hover{border-color:#E54B2C;background:rgba(229,75,44,.06);}' +
				'.ws-choose-site-icon{position:relative;width:18px;height:18px;flex:0 0 18px;}' +
				'.ws-choose-site-icon:before{content:"";position:absolute;left:4px;top:1px;width:10px;height:10px;background:#E54B2C;border-radius:50% 50% 50% 0;transform:rotate(-45deg);}' +
				'.ws-choose-site-icon:after{content:"";position:absolute;left:8px;top:5px;width:3px;height:3px;border-radius:50%;background:#fff;}' +
				'.ws-choose-site-title{font-size:16px;font-weight:800;color:#202124;line-height:1.25;}' +
				'.ws-site-address-box.ws-has-address>.ws-choose-site-address{display:none;}' +
				'.ws-address-summary{margin-bottom:12px;}' +
				'.ws-address-summary:empty{display:none;}' +
				'.ws-summary-card{border:1px solid #dfe3e8;border-radius:8px;background:#fff;padding:12px;}' +
				'.ws-summary-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:7px;}' +
				'.ws-summary-title{font-size:12px;font-weight:800;color:#6b7280;text-transform:uppercase;margin-bottom:7px;}' +
				'.ws-summary-header .ws-summary-title{margin-bottom:0;}' +
				'.ws-summary-change{border:1px solid #E54B2C;border-radius:8px;background:#fff;color:#E54B2C;font-size:13px;font-weight:800;padding:6px 12px;line-height:1.2;white-space:nowrap;}' +
				'.ws-summary-change:focus{outline:none;box-shadow:0 0 0 3px rgba(229,75,44,.18);border-radius:8px;}' +
				'.ws-summary-area{font-size:16px;font-weight:800;color:#202124;line-height:1.3;margin-bottom:10px;}' +
				'.ws-summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;border-top:1px solid #eef0f2;padding-top:10px;}' +
				'.ws-summary-item{min-width:0;}' +
				'.ws-summary-label{display:block;font-size:11px;font-weight:800;color:#667085;text-transform:uppercase;line-height:1.2;margin-bottom:2px;}' +
				'.ws-summary-value{display:block;font-size:13px;font-weight:700;color:#202124;line-height:1.35;word-break:break-word;}' +
				'.ws-summary-directions{margin-top:10px;border-top:1px solid #eef0f2;padding-top:10px;font-size:13px;color:#344054;line-height:1.45;}' +
				'.ws-location-error{display:none;margin-top:8px;color:#b42318;font-size:13px;font-weight:600;}' +
				'.ws-location-overlay{position:fixed;z-index:99999;left:0;right:0;top:var(--ws-location-top,0px);bottom:auto;width:100vw;height:var(--ws-location-height,100vh);max-height:var(--ws-location-height,100vh);overflow:hidden;background:#fff;color:#202124;overscroll-behavior:contain;}' +
				'.ws-location-screen{position:relative;height:var(--ws-location-height,100vh);max-height:var(--ws-location-height,100vh);min-height:0;display:flex;flex-direction:column;background:#fff;overflow:hidden;}' +
				'.ws-location-header{min-height:76px;display:flex;align-items:center;gap:16px;padding:calc(12px + env(safe-area-inset-top)) 18px 12px 18px;background:#fff;border-bottom:1px solid #eef0f2;}' +
				'.ws-location-heading{font-size:22px;font-weight:800;line-height:1.2;flex:1;}' +
				'.ws-location-back,.ws-address-back,.ws-location-search-toggle{width:48px;height:48px;border:1px solid #e4e7ec;border-radius:50%;background:#fff;position:relative;flex:0 0 48px;}' +
				'.ws-location-back:before,.ws-address-back:before{content:"";position:absolute;left:18px;top:15px;width:14px;height:14px;border-left:2px solid #202124;border-bottom:2px solid #202124;transform:rotate(45deg);}' +
				'.ws-location-search-toggle:before{content:"";position:absolute;left:15px;top:14px;width:15px;height:15px;border:2px solid #202124;border-radius:50%;}' +
				'.ws-location-search-toggle:after{content:"";position:absolute;left:29px;top:29px;width:10px;height:2px;background:#202124;transform:rotate(45deg);transform-origin:left center;}' +
				'.ws-location-header-space{width:48px;flex:0 0 48px;}' +
				'.ws-search-panel{position:absolute;left:12px;right:12px;top:84px;z-index:5;}' +
				'.ws-map-search{height:46px;width:100%;border:1px solid #d7dce2;border-radius:8px;background:#fff;padding:8px 42px 8px 12px;font-size:16px;box-shadow:0 4px 14px rgba(0,0,0,.16);}' +
				'.ws-clear-search{position:absolute;right:7px;top:50%;width:32px;height:32px;margin-top:-16px;border:0;border-radius:50%;background:#eef1f5;}' +
				'.ws-clear-search:before,.ws-clear-search:after{content:"";position:absolute;left:9px;top:15px;width:14px;height:2px;background:#5e6c84;}' +
				'.ws-clear-search:before{transform:rotate(45deg);}.ws-clear-search:after{transform:rotate(-45deg);}' +
				'.ws-map-stage{position:relative;flex:1 1 auto;min-height:0;background:#edf1f5;}' +
				'.ws-map-canvas{position:absolute;left:0;right:0;top:0;bottom:0;}' +
				'.ws-center-pin{position:absolute;left:50%;top:50%;width:34px;height:34px;margin-left:-17px;margin-top:-34px;background:#E54B2C;border-radius:50% 50% 50% 0;transform:rotate(-45deg);box-shadow:0 2px 5px rgba(0,0,0,.25);z-index:3;pointer-events:none;}' +
				'.ws-center-pin:before{content:"";position:absolute;left:10px;top:10px;width:14px;height:14px;border-radius:50%;background:#fff;}' +
				'.ws-center-pin:after{content:"";position:absolute;left:23px;top:23px;width:11px;height:5px;border-radius:50%;background:rgba(0,0,0,.35);transform:rotate(45deg);}' +
				'.ws-center-callout{position:absolute;left:50%;top:50%;z-index:4;transform:translate(-50%,-98px);background:#242424;color:#fff;border-radius:8px;padding:11px 15px;font-size:15px;font-weight:600;white-space:nowrap;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,.25);}' +
				'.ws-center-callout:after{content:"";position:absolute;left:50%;bottom:-10px;margin-left:-10px;border-left:10px solid transparent;border-right:10px solid transparent;border-top:10px solid #242424;}' +
				'.ws-current-location{position:absolute;right:18px;bottom:22px;width:54px;height:54px;border:3px solid #fff;border-radius:50%;background:#E54B2C;z-index:5;box-shadow:0 4px 14px rgba(0,0,0,.28);}' +
				'.ws-current-location:before{content:"";position:absolute;left:15px;top:10px;width:18px;height:18px;background:#fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);}' +
				'.ws-current-location:after{content:"";position:absolute;left:21px;top:16px;width:6px;height:6px;border-radius:50%;background:#E54B2C;}' +
				'.ws-current-location:disabled{opacity:.7;cursor:wait;}' +
				'.ws-map-footer,.ws-address-footer{flex:0 0 auto;padding:16px 18px calc(24px + env(safe-area-inset-bottom)) 18px;background:#fff;border-top:1px solid #eef0f2;}' +
				'.ws-map-status{min-height:18px;margin-bottom:8px;color:#4b5563;font-size:13px;font-weight:600;text-align:center;}' +
				'.ws-address-content{flex:1;overflow:auto;padding:18px 18px 100px 18px;}' +
				'.ws-preview-map{height:150px;border-radius:0;background:#edf1f5;margin-bottom:14px;overflow:hidden;}' +
				'.ws-area-card{display:flex;align-items:center;gap:12px;border:1px solid #e4e7ec;border-radius:8px;padding:11px 12px;margin-bottom:16px;background:#fff;}' +
				'.ws-area-card>div{flex:1;min-width:0;}.ws-area-label{font-size:13px;color:#6b7280;font-weight:700;margin-bottom:3px;}' +
				'.ws-area-icon{width:18px;height:18px;border-radius:50% 50% 50% 0;background:#6b7280;transform:rotate(-45deg);flex:0 0 18px;}' +
				'.ws-area-icon:before{content:"";position:absolute;left:6px;top:6px;width:6px;height:6px;background:#fff;border-radius:50%;}' +
				'.ws-change-location{border:0;background:#fff;color:#E54B2C;font-size:14px;font-weight:700;}' +
				'.ws-address-type-row{display:flex;gap:10px;margin-bottom:14px;overflow:auto;}' +
				'.ws-address-type{border:1px solid #e4e7ec;border-radius:8px;background:#fff;color:#202124;font-size:14px;font-weight:700;padding:11px 14px;white-space:nowrap;}' +
				'.ws-address-type.active{background:#202124;color:#fff;border-color:#202124;}' +
				'.ws-input-wrap{display:block;position:relative;margin-bottom:12px;}' +
				'.ws-input-label{display:block;font-size:12px;font-weight:800;color:#667085;line-height:1.2;margin:0 0 5px 2px;}' +
				'.ws-address-input{width:100%;border:1px solid #e4e7ec;border-radius:8px;background:#fff;color:#202124;font-size:16px;padding:14px 14px;box-shadow:none;}' +
				'.ws-address-input:focus{outline:none;border-color:#E54B2C;box-shadow:0 0 0 2px rgba(229,75,44,.13);}' +
				'.ws-address-input.ws-input-error{border-color:#d92d20;background:#fffafa;}' +
				'.ws-address-error{margin:2px 0 14px 0;border:1px solid #fecdca;border-radius:8px;background:#fffbfa;color:#b42318;font-size:13px;font-weight:700;line-height:1.45;padding:10px 12px;}' +
				'.ws-two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px;}' +
				'.pac-container{z-index:100000!important;}' +
				'html.ws-location-open,body.ws-location-open{overflow:hidden;overscroll-behavior:none;}' +
				'@media(min-width:768px){.ws-location-screen{max-width:520px;margin:0 auto;border-left:1px solid #e4e7ec;border-right:1px solid #e4e7ec;}.ws-location-overlay{background:rgba(17,24,39,.42);}.ws-map-stage{min-height:480px;}}' +
				'@media(max-width:420px){.ws-location-heading{font-size:20px;}.ws-location-header{min-height:68px;padding:calc(10px + env(safe-area-inset-top)) 14px 10px 14px;gap:12px;}.ws-location-back,.ws-address-back,.ws-location-search-toggle{width:44px;height:44px;flex-basis:44px;}.ws-center-callout{font-size:13px;padding:10px 12px;}.ws-two-col{gap:8px;}.ws-address-input{font-size:16px;padding:13px 12px;}.ws-input-label{font-size:11px;}}' +
			'</style>'
		);

		this.$wrapper = wrapper;
		this.$choose_button = wrapper.find(".ws-choose-site-address");
		this.$summary = wrapper.find(".ws-address-summary");
		this.$location_error = wrapper.find(".ws-location-error");
		this.$overlay = wrapper.find(".ws-location-overlay");
		this.$map_screen = wrapper.find(".ws-map-screen");
		this.$address_screen = wrapper.find(".ws-address-screen");
		this.$map_canvas = wrapper.find(".ws-map-canvas");
		this.$preview_map = wrapper.find(".ws-preview-map");
		this.$search_panel = wrapper.find(".ws-search-panel");
		this.$search = wrapper.find(".ws-map-search");
		this.$status = wrapper.find(".ws-map-status");
		this.$fill_address = wrapper.find(".ws-fill-address");
		this.$confirm_address = wrapper.find(".ws-confirm-address");
		this.$current_location = wrapper.find(".ws-current-location");
		this.$address_error = wrapper.find(".ws-address-error");
	},

	bind: function() {
		var me = this;

		me.$choose_button.on("click", function() {
			me.open_map_step();
		});

		me.$wrapper.on("click", ".ws-summary-change", function() {
			me.open_map_step();
		});

		me.$wrapper.find(".ws-location-back").on("click", function() {
			me.close_overlay();
		});

		me.$wrapper.find(".ws-location-search-toggle").on("click", function() {
			me.$search_panel.toggle();
			me.$search.focus();
		});

		me.$wrapper.find(".ws-clear-search").on("click", function() {
			me.$search.val("").focus();
		});

		me.$wrapper.find(".ws-current-location").on("click", function() {
			me.use_current_location();
		});

		me.$wrapper.find(".ws-fill-address").on("click", function() {
			me.confirm_map_location();
		});

		me.$wrapper.find(".ws-address-back").on("click", function() {
			me.show_map_step();
		});

		me.$wrapper.find(".ws-change-location").on("click", function() {
			me.show_map_step();
		});

		me.$wrapper.find(".ws-address-type").on("click", function() {
			me.$wrapper.find(".ws-address-type").removeClass("active");
			$(this).addClass("active");
		});

		me.$wrapper.find(".ws-confirm-address").on("click", function() {
			me.confirm_complete_address();
		});

		me.$wrapper.on("input change", ".ws-address-input", function() {
			me.clear_address_error();
		});
	},

	bind_viewport_events: function() {
		var me = this;

		if (me.viewport_events_bound) {
			me.update_location_viewport();
			return;
		}

		me.viewport_events_bound = true;
		me.update_location_viewport();

		$(window).on("resize.ws_location_picker orientationchange.ws_location_picker", function() {
			me.update_location_viewport();
			me.resize_active_maps();
		});

		if (window.visualViewport) {
			window.visualViewport.addEventListener("resize", function() {
				me.update_location_viewport();
				me.resize_active_maps();
			});
			window.visualViewport.addEventListener("scroll", function() {
				me.update_location_viewport();
			});
		}
	},

	update_location_viewport: function() {
		var viewport = window.visualViewport;
		var height = viewport && viewport.height ? viewport.height : window.innerHeight;
		var top = viewport && viewport.offsetTop ? viewport.offsetTop : 0;

		if (!height) {
			height = document.documentElement.clientHeight || 0;
		}

		document.documentElement.style.setProperty("--ws-location-height", Math.max(320, Math.floor(height)) + "px");
		document.documentElement.style.setProperty("--ws-location-top", Math.max(0, Math.floor(top)) + "px");
	},

	resize_active_maps: function() {
		var me = this;

		if (!me.$overlay || !me.$overlay.is(":visible") || !window.google || !google.maps) {
			return;
		}

		setTimeout(function() {
			if (me.map && me.$map_screen.is(":visible")) {
				google.maps.event.trigger(me.map, "resize");
				me.map.setCenter(me.get_current_position());
			}

			if (me.preview_map && me.$address_screen.is(":visible")) {
				google.maps.event.trigger(me.preview_map, "resize");
				me.preview_map.setCenter(me.get_current_position());
			}
		}, 80);
	},

	load_google_maps: function(callback) {
		var me = this;

		if (window.google && google.maps && google.maps.places) {
			callback();
			return;
		}

		if (me.google_maps_loading) {
			me.google_maps_callbacks.push(callback);
			return;
		}

		me.google_maps_loading = true;
		me.google_maps_callbacks = [callback];

		var callback_name = "ws_google_maps_loaded_" + new Date().getTime();
		window[callback_name] = function() {
			var callbacks = me.google_maps_callbacks || [];

			me.google_maps_loading = false;
			me.google_maps_callbacks = [];

			$.each(callbacks, function(i, queued_callback) {
				queued_callback();
			});

			delete window[callback_name];
		};

		var script = document.createElement("script");
		script.src = "https://maps.googleapis.com/maps/api/js?key=" +
			encodeURIComponent(this.opts.api_key) +
			"&libraries=places&language=en&region=BH&callback=" + callback_name;
		script.async = true;
		script.defer = true;
		script.onerror = function() {
			me.google_maps_loading = false;
			me.google_maps_callbacks = [];
			me.show_message("Could not load Google Maps. Please check your connection and try again.");
			delete window[callback_name];
		};
		document.head.appendChild(script);
	},

	open_map_step: function() {
		var me = this;

		me.$location_error.hide().text("");
		me.update_location_viewport();
		me.$overlay.show();
		$("html, body").addClass("ws-location-open");
		me.show_map_step();

		me.load_google_maps(function() {
			me.setup_map();
			setTimeout(function() {
				google.maps.event.trigger(me.map, "resize");
				me.map.setCenter(me.get_current_position());
			}, 80);
		});
	},

	close_overlay: function() {
		this.$overlay.hide();
		$("html, body").removeClass("ws-location-open");
	},

	show_map_step: function() {
		this.$address_screen.hide();
		this.$map_screen.css("display", "flex");
		if (this.map && window.google) {
			google.maps.event.trigger(this.map, "resize");
			this.map.setCenter(this.get_current_position());
		}
	},

	show_address_step: function() {
		this.$map_screen.hide();
		this.$address_screen.css("display", "flex");
		this.populate_address_inputs();
		this.setup_preview_map();
	},

	setup_map: function() {
		var me = this;
		var center = me.get_current_position();

		if (me.map) {
			me.map.setCenter(center);
			return;
		}

		me.geocoder = new google.maps.Geocoder();

		me.map = new google.maps.Map(me.$map_canvas[0], {
			center: center,
			zoom: me.opts.default_zoom,
			mapTypeControl: false,
			streetViewControl: false,
			fullscreenControl: false,
			gestureHandling: "greedy"
		});

		me.autocomplete = new google.maps.places.Autocomplete(me.$search[0], {
			fields: ["formatted_address", "geometry", "place_id", "name", "address_components"],
			componentRestrictions: { country: "bh" }
		});

		me.autocomplete.addListener("place_changed", function() {
			var place = me.autocomplete.getPlace();

			if (!place.geometry || !place.geometry.location) {
				me.show_message("Please select a location from Google suggestions.");
				return;
			}

			me.selected_address = place.formatted_address || place.name || "";
			me.selected_place_id = place.place_id || "";
			me.set_detected_address_from_components(place.address_components);
			me.map.setCenter(place.geometry.location);
			me.map.setZoom(17);
			me.$search_panel.hide();
			me.show_message("Location found. Move the map if needed.");
		});

		google.maps.event.addListener(me.map, "dragstart", function() {
			me.clear_detected_location_details();
			me.set_value(me.opts.method_field, "Map Pin");
		});
	},

	confirm_map_location: function() {
		var me = this;
		var center;

		if (!me.map) {
			me.show_message("Map is still loading. Please wait.");
			return;
		}

		center = me.map.getCenter();
		me.selected_lat = center.lat();
		me.selected_lng = center.lng();
		me.set_value(me.opts.method_field, me.get_value(me.opts.method_field) || "Map Pin");
		me.show_message("Saving selected location...");
		me.set_button_loading(me.$fill_address, true, "Saving...");

		me.reverse_geocode(me.selected_lat, me.selected_lng, function() {
			if (!me.selected_city) {
				me.set_button_loading(me.$fill_address, false, "Fill Complete Address");
				me.show_message("Could not detect Area / City for this point. Please move the map slightly or search the area name.");
				return;
			}

			me.update_location_fields();
			me.set_button_loading(me.$fill_address, false, "Fill Complete Address");
			me.show_address_step();
		});
	},

	use_current_location: function() {
		var me = this;

		if (!me.map) {
			me.show_message("Map is still loading. Please wait.");
			return;
		}

		if (!navigator.geolocation) {
			me.show_message("Current location is not supported on this browser.");
			return;
		}

		if (window.isSecureContext === false) {
			me.show_message("Current location requires HTTPS. Please open this form using a secure link.");
			return;
		}

		me.show_message("Detecting current location...");
		me.set_button_loading(me.$current_location, true);

		navigator.geolocation.getCurrentPosition(function(position) {
			var current_position = {
				lat: position.coords.latitude,
				lng: position.coords.longitude
			};

			me.set_value(me.opts.method_field, "Current Location");
			me.clear_detected_location_details();
			me.map.setCenter(current_position);
			me.map.setZoom(17);
			me.show_message("Current location found. Move the map if needed.");
			me.set_button_loading(me.$current_location, false);
		}, function(error) {
			var message = "Could not detect current location. Please search or move the map.";

			if (error && error.code === error.PERMISSION_DENIED) {
				message = "Location permission was denied. Please allow location access in your browser settings.";
			} else if (error && error.code === error.POSITION_UNAVAILABLE) {
				message = "Current location is unavailable. Please try again or search your area.";
			} else if (error && error.code === error.TIMEOUT) {
				message = "Current location is taking too long. Please try again near a window.";
			}

			me.show_message(message);
			me.set_button_loading(me.$current_location, false);
		}, {
			enableHighAccuracy: true,
			timeout: 30000,
			maximumAge: 0
		});
	},

	reverse_geocode: function(lat, lng, callback) {
		var me = this;

		if (!me.geocoder) {
			callback();
			return;
		}

		me.geocoder.geocode({ location: { lat: lat, lng: lng } }, function(results, status) {
			if (status === "OK" && results && results.length) {
				me.selected_address = results[0].formatted_address || me.selected_address || "";
				me.selected_place_id = results[0].place_id || me.selected_place_id || "";
				me.set_detected_address_from_components(results[0].address_components);
				me.selected_city = me.selected_city || me.get_city_from_formatted_address(me.selected_address);
			}

			callback();
		});
	},

	update_location_fields: function() {
		var lat = this.selected_lat;
		var lng = this.selected_lng;
		var link = "https://www.google.com/maps?q=" + lat + "," + lng;

		this.set_value(this.opts.latitude_field, lat);
		this.set_value(this.opts.longitude_field, lng);
		this.set_value(this.opts.address_field, this.selected_address || "");
		this.set_value(this.opts.place_id_field, this.selected_place_id || "");
		this.set_value(this.opts.maps_link_field, link);
		this.set_value(this.opts.city_field, this.selected_city || "");
		this.set_value(this.opts.road_no_field, this.selected_road_no || "");
		this.set_value(this.opts.block_field, this.selected_block || "");
	},

	setup_preview_map: function() {
		var me = this;
		var position = me.get_current_position();

		if (!window.google || !google.maps) {
			return;
		}

		if (!me.preview_map) {
			me.preview_map = new google.maps.Map(me.$preview_map[0], {
				center: position,
				zoom: 16,
				disableDefaultUI: true,
				draggable: false,
				scrollwheel: false,
				gestureHandling: "none"
			});

			me.preview_marker = new google.maps.Marker({
				position: position,
				map: me.preview_map
			});
		}

		setTimeout(function() {
			google.maps.event.trigger(me.preview_map, "resize");
			me.preview_map.setCenter(position);
			me.preview_marker.setPosition(position);
		}, 80);
	},

	populate_address_inputs: function() {
		var parsed_notes = this.parse_address_notes(this.get_value(this.opts.directions_field));

		this.$wrapper.find(".ws-city-input").val(this.selected_city || this.get_value(this.opts.city_field));
		this.$wrapper.find(".ws-building-input").val(this.get_value(this.opts.building_no_field));
		this.$wrapper.find(".ws-flat-input").val(this.get_value(this.opts.flat_no_field));
		this.$wrapper.find(".ws-road-input").val(this.selected_road_no || this.get_value(this.opts.road_no_field));
		this.$wrapper.find(".ws-block-input").val(this.selected_block || this.get_value(this.opts.block_field));
		this.$wrapper.find(".ws-directions-input").val(parsed_notes.notes);
		this.$wrapper.find(".ws-address-type").removeClass("active");
		this.get_address_type_button(parsed_notes.address_type).addClass("active");
	},

	confirm_complete_address: function() {
		var missing = [];
		var city = $.trim(this.$wrapper.find(".ws-city-input").val());
		var flat_no = $.trim(this.$wrapper.find(".ws-flat-input").val());
		var road_no = $.trim(this.$wrapper.find(".ws-road-input").val());
		var block = $.trim(this.$wrapper.find(".ws-block-input").val());
		var directions = $.trim(this.$wrapper.find(".ws-directions-input").val());
		var address_type = this.$wrapper.find(".ws-address-type.active").attr("data-address-type") || "House";
		var first_missing_input = null;

		if (!city) {
			missing.push("Area / City");
			first_missing_input = first_missing_input || this.$wrapper.find(".ws-city-input");
		}
		if (!flat_no) {
			missing.push("Flat / Home");
			first_missing_input = first_missing_input || this.$wrapper.find(".ws-flat-input");
		}
		if (!road_no) {
			missing.push("Road / Street No");
			first_missing_input = first_missing_input || this.$wrapper.find(".ws-road-input");
		}
		if (!block) {
			missing.push("Block");
			first_missing_input = first_missing_input || this.$wrapper.find(".ws-block-input");
		}

		if (missing.length) {
			this.show_address_error(missing, first_missing_input);
			return;
		}

		this.clear_address_error();

		this.confirmed_address = {
			city: city,
			address_type: address_type,
			building_no: $.trim(this.$wrapper.find(".ws-building-input").val()),
			flat_no: flat_no,
			road_no: road_no,
			block: block,
			directions: directions
		};

		this.set_value(this.opts.city_field, city);
		this.set_value(this.opts.building_no_field, this.confirmed_address.building_no);
		this.set_value(this.opts.flat_no_field, flat_no);
		this.set_value(this.opts.road_no_field, road_no);
		this.set_value(this.opts.block_field, block);
		this.set_value(this.opts.directions_field, directions);
		this.set_value(this.opts.country_field, this.get_value(this.opts.country_field) || "Bahrain");
		this.render_summary();
		this.close_overlay();
	},

	show_address_error: function(missing, $first_input) {
		var message = "Please complete: " + missing.join(", ");

		this.$wrapper.find(".ws-address-input").removeClass("ws-input-error");

		if ($first_input && $first_input.length) {
			$first_input.addClass("ws-input-error");
			$first_input.focus();
		}

		this.$address_error.text(message).show();
		this.$address_error[0].scrollIntoView({
			behavior: "smooth",
			block: "nearest"
		});
	},

	clear_address_error: function() {
		this.$wrapper.find(".ws-address-input").removeClass("ws-input-error");
		this.$address_error.hide().text("");
	},

	wrap_validation: function() {
		var me = this;
		var existing_validate = frappe.web_form.validate;

		frappe.web_form.validate = function() {
			var result = true;

			if (!me.has_confirmed_location()) {
				frappe.msgprint({
					title: __("Required Fields Missing"),
					indicator: "red",
					message: "Please choose and confirm the site address before submitting."
				});
				me.$location_error.text("Please choose and confirm the site address.").show();
				return false;
			}

			if (existing_validate) {
				result = existing_validate.apply(frappe.web_form, arguments);
			}

			if (!result) {
				return false;
			}

			return true;
		};
	},

	has_confirmed_location: function() {
		return Boolean(
			this.get_value(this.opts.latitude_field) &&
			this.get_value(this.opts.longitude_field) &&
			this.get_value(this.opts.maps_link_field) &&
			this.get_value(this.opts.method_field)
		);
	},

	render_summary: function() {
		var saved_address = this.get_summary_address_values();
		var city = saved_address.city;
		var building_no = saved_address.building_no;
		var flat_no = saved_address.flat_no;
		var road_no = saved_address.road_no;
		var block = saved_address.block;
		var location_address = this.get_value(this.opts.address_field);
		var parsed_notes = {
			address_type: saved_address.address_type,
			notes: saved_address.directions
		};
		var details = [];
		var details_html = "";

		if (!this.has_confirmed_location()) {
			this.$summary.html("");
			this.$wrapper.find(".ws-site-address-box").removeClass("ws-has-address");
			this.set_choose_button_text("Choose Site Address");
			return;
		}

		if (parsed_notes.address_type) {
			details.push({ label: "Type", value: parsed_notes.address_type });
		}
		if (building_no) {
			details.push({ label: "Building", value: building_no });
		}
		if (flat_no) {
			details.push({ label: "Flat / Home", value: flat_no });
		}
		if (road_no) {
			details.push({ label: "Road / Street", value: road_no });
		}
		if (block) {
			details.push({ label: "Block", value: block });
		}

		$.each(details, function(i, row) {
			details_html += '<div class="ws-summary-item">' +
				'<span class="ws-summary-label">' + $("<div>").text(row.label).html() + '</span>' +
				'<span class="ws-summary-value">' + $("<div>").text(row.value).html() + '</span>' +
			'</div>';
		});

		this.$summary.html(
			'<div class="ws-summary-card">' +
				'<div class="ws-summary-header">' +
					'<div class="ws-summary-title">Selected Site Address</div>' +
					'<button type="button" class="ws-summary-change">Change</button>' +
				'</div>' +
				'<div class="ws-summary-area">' + this.escape_html(city || location_address || "Location selected") + '</div>' +
				(details_html ? '<div class="ws-summary-grid">' + details_html + '</div>' : '') +
				(parsed_notes.notes ? '<div class="ws-summary-directions">' +
					'<span class="ws-summary-label">Additional Directions</span>' +
					this.escape_html(parsed_notes.notes).replace(/\n/g, "<br>") +
				'</div>' : '') +
			'</div>'
		);
		this.$wrapper.find(".ws-site-address-box").addClass("ws-has-address");
		this.set_choose_button_text("Change Site Address");
	},

	get_summary_address_values: function() {
		var parsed_notes;

		if (this.confirmed_address) {
			return this.confirmed_address;
		}

		parsed_notes = this.parse_address_notes(this.get_value(this.opts.directions_field));

		return {
			city: this.get_value(this.opts.city_field),
			address_type: parsed_notes.address_type,
			building_no: this.get_value(this.opts.building_no_field),
			flat_no: this.get_value(this.opts.flat_no_field),
			road_no: this.get_value(this.opts.road_no_field),
			block: this.get_value(this.opts.block_field),
			directions: parsed_notes.notes
		};
	},

	set_choose_button_text: function(title) {
		this.$choose_button.find(".ws-choose-site-title").text(title || "");
	},

	parse_address_notes: function(notes) {
		var parsed = {
			address_type: "House",
			notes: ""
		};
		var clean_lines = [];

		$.each((notes || "").split(/\n/), function(i, line) {
			var address_type_match = line.match(/^Address Type:\s*(.+)$/i);

			if (address_type_match && address_type_match[1]) {
				parsed.address_type = address_type_match[1];
				return;
			}

			if ($.trim(line)) {
				clean_lines.push(line);
			}
		});

		parsed.notes = clean_lines.join("\n");
		return parsed;
	},

	get_address_type_button: function(address_type) {
		var $button = this.$wrapper.find(".ws-address-type").filter(function() {
			return $(this).attr("data-address-type") === address_type;
		});

		if (!$button.length) {
			$button = this.$wrapper.find('.ws-address-type[data-address-type="House"]');
		}

		return $button;
	},

	set_button_loading: function($button, is_loading, label) {
		if (!$button || !$button.length) {
			return;
		}

		if (label) {
			$button.text(label);
		}

		$button.prop("disabled", Boolean(is_loading));
	},

	get_current_position: function() {
		var lat = parseFloat(this.get_value(this.opts.latitude_field));
		var lng = parseFloat(this.get_value(this.opts.longitude_field));

		if (this.selected_lat && this.selected_lng) {
			return { lat: this.selected_lat, lng: this.selected_lng };
		}

		if (!isNaN(lat) && !isNaN(lng)) {
			return { lat: lat, lng: lng };
		}

		return {
			lat: this.opts.default_lat,
			lng: this.opts.default_lng
		};
	},

	set_value: function(fieldname, value) {
		if (fieldname && frappe.web_form.fields_dict[fieldname]) {
			frappe.web_form.set_value(fieldname, value || "");
			if (frappe.web_form.doc) {
				frappe.web_form.doc[fieldname] = value || "";
			}
		}
	},

	get_value: function(fieldname) {
		if (fieldname && frappe.web_form.fields_dict[fieldname]) {
			return frappe.web_form.get_value(fieldname) || "";
		}

		return "";
	},

	clear_detected_location_details: function() {
		this.selected_address = "";
		this.selected_place_id = "";
		this.selected_city = "";
		this.selected_road_no = "";
		this.selected_block = "";
	},

	set_detected_address_from_components: function(components) {
		this.selected_city = this.get_city_from_components(components);
		this.selected_road_no = this.get_road_no_from_components(components);
		this.selected_block = this.get_block_from_components(components);
	},

	set_city_from_components: function(components) {
		var city = this.get_city_from_components(components);

		if (city) {
			this.set_value(this.opts.city_field, city);
		}
	},

	set_road_no_from_components: function(components) {
		var road_no = this.get_road_no_from_components(components);

		if (road_no) {
			this.set_value(this.opts.road_no_field, road_no);
		}
	},

	set_block_from_components: function(components) {
		var block = this.get_block_from_components(components);

		if (block) {
			this.set_value(this.opts.block_field, block);
		}
	},

	get_city_from_components: function(components) {
		var priority = [
			"locality",
			"sublocality",
			"sublocality_level_1",
			"administrative_area_level_2",
			"administrative_area_level_1"
		];
		var match = "";

		components = components || [];

		$.each(priority, function(i, type) {
			if (match) {
				return false;
			}

			$.each(components, function(j, component) {
				if (component.types && component.types.indexOf(type) !== -1) {
					match = component.long_name || "";
					return false;
				}
			});
		});

		return match;
	},

	get_city_from_formatted_address: function(address) {
		var parts = [];
		var ignored = {
			"bahrain": true,
			"kingdom of bahrain": true
		};

		$.each((address || "").split(","), function(i, part) {
			var clean = $.trim(part);
			var clean_lower = clean.toLowerCase();

			if (!clean || ignored[clean_lower]) {
				return;
			}

			if (/^\d+$/.test(clean) || /\b(?:road|rd|block|blk)\b/i.test(clean)) {
				return;
			}

			parts.push(clean);
		});

		return parts.length ? parts[0] : "";
	},

	get_road_no_from_components: function(components) {
		var road_name = this.get_component_long_name(components, "route");
		var match;

		if (!road_name) {
			return "";
		}

		match = road_name.match(/\b(?:rd|road)\s*(?:no\.?|number)?\s*(\d{1,5})\b/i);

		if (match && match[1]) {
			return match[1];
		}

		return "";
	},

	get_block_from_components: function(components) {
		var types = [
			"sublocality",
			"sublocality_level_1",
			"neighborhood",
			"administrative_area_level_3"
		];
		var block = "";
		var me = this;

		$.each(types, function(i, type) {
			var name;
			var match;

			if (block) {
				return false;
			}

			name = me.get_component_long_name(components, type);
			match = name && name.match(/\b(?:block|blk)\s*(\d{1,5})\b/i);

			if (match && match[1]) {
				block = match[1];
				return false;
			}
		});

		return block;
	},

	get_component_long_name: function(components, type) {
		var value = "";

		components = components || [];

		$.each(components, function(i, component) {
			if (component.types && component.types.indexOf(type) !== -1) {
				value = component.long_name || "";
				return false;
			}
		});

		return value;
	},

	show_message: function(message) {
		if (this.$status && this.$status.length) {
			this.$status.text(message || "");
		}
	},

	show_error: function(message) {
		if (this.$location_error && this.$location_error.length) {
			this.$location_error.text(message || "").toggle(Boolean(message));
		}
	},

	escape_html: function(value) {
		return $("<div>").text(value || "").html();
	}
};
