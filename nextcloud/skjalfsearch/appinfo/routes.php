<?php

return [
	'api' => [
		['method' => 'GET', 'url' => '/api/v1/search', 'name' => 'SearchController#search'],
		['method' => 'POST', 'url' => '/api/v1/search', 'name' => 'SearchController#search'],
		['method' => 'POST', 'url' => '/api/v1/embed/file/{fileId}', 'name' => 'SearchController#embedFile'],
		['method' => 'POST', 'url' => '/api/v1/embed/folder/{folderId}', 'name' => 'SearchController#embedFolder'],
		['method' => 'GET', 'url' => '/api/v1/status/{fileId}', 'name' => 'SearchController#status'],
		['method' => 'GET', 'url' => '/api/v1/folders', 'name' => 'SearchController#getFolders'],
		['method' => 'POST', 'url' => '/api/v1/folders', 'name' => 'SearchController#registerFolder'],
		['method' => 'GET', 'url' => '/api/v1/thumbnail/{fileId}', 'name' => 'SearchController#getThumbnail'],
	],
];
