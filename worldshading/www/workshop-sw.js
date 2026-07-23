var CACHE_NAME = "ws-workshop-v5";
var APP_SHELL = [
    "/workshop",
    "/workshop/manifest.json",
    "/ws-pwa-core.css?v=2",
    "/ws-pwa-core.js?v=3"
];

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(APP_SHELL);
        }).catch(function () {
            return Promise.resolve();
        })
    );
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.map(function (key) {
                if (key !== CACHE_NAME) {
                    return caches.delete(key);
                }
                return Promise.resolve();
            }));
        }).then(function () {
            return self.clients.claim();
        })
    );
});

self.addEventListener("fetch", function (event) {
    var request_url = new URL(event.request.url);

    if (request_url.pathname.indexOf("/api/") === 0) {
        return;
    }

    if (event.request.method !== "GET") {
        return;
    }

    event.respondWith(
        fetch(event.request).then(function (response) {
            var response_clone = response.clone();
            caches.open(CACHE_NAME).then(function (cache) {
                cache.put(event.request, response_clone);
            });
            return response;
        }).catch(function () {
            return caches.match(event.request).then(function (cached) {
                return cached || caches.match("/workshop");
            });
        })
    );
});

self.addEventListener("push", function (event) {
    var data = {};

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data = {
                body: event.data.text()
            };
        }
    }

    event.waitUntil(
        self.registration.showNotification(data.title || "World Shading", {
            body: data.body || "",
            icon: "/files/logo%20removed.png",
            badge: "/files/logo%20removed.png",
            tag: data.tag || "workshop",
            data: {
                url: data.url || "/workshop"
            }
        })
    );
});

self.addEventListener("notificationclick", function (event) {
    var url = "/workshop";

    event.notification.close();

    if (event.notification.data && event.notification.data.url) {
        url = event.notification.data.url;
    }

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function (client_list) {
            for (var i = 0; i < client_list.length; i++) {
                var client = client_list[i];

                if (client.url.indexOf("/workshop") !== -1 && "focus" in client) {
                    return client.focus();
                }
            }

            if (clients.openWindow) {
                return clients.openWindow(url);
            }

            return Promise.resolve();
        })
    );
});
