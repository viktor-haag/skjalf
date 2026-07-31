<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\Skjalfsearch\Controller;

use Exception;

/**
 * Lightweight HTTP client for the Python embedder service.
 *
 * The embedder service runs as a separate process and exposes a REST API
 * for embedding generation and semantic search.
 */
class APIClient {
	private string $baseUrl;
	private int $timeout;

	public function __construct(?string $baseUrl = null, int $timeout = 30) {
		$this->baseUrl = $baseUrl ?? $this->resolveBaseUrl();
		$this->timeout = $timeout;
	}

	/**
	 * Resolve the embedder service base URL from app config.
	 */
	private function resolveBaseUrl(): string {
		$appConfig = \OC::$server->getAppConfig();
		$url = $appConfig->getValue('skjalfsearch', 'embedder_url');
		if ($url !== '') {
			return rtrim($url, '/');
		}
		// Default: service runs on localhost
		return 'http://embedder-service:8101';                                                                                          

	}

	/**
	 * Send an HTTP request to the embedder service.
	 *
	 * @param string $method HTTP method
	 * @param string $endpoint API endpoint (e.g., '/api/v1/embed')
	 * @param array $body Request body (will be JSON-encoded)
	 * @return array Decoded JSON response
	 * @throws Exception If the request fails
	 */
	private function request(string $method, string $endpoint, array $body = []): array {
		$url = $this->baseUrl . $endpoint;

		$ch = curl_init($url);
		curl_setopt_array($ch, [
			CURLOPT_CUSTOMREQUEST => $method,
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_TIMEOUT => $this->timeout,
			CURLOPT_HTTPHEADER => [
				'Content-Type: application/json',
				'Accept: application/json',
			],
		]);

		if ($method === 'POST' || $method === 'PUT') {
			curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
		}

		$response = curl_exec($ch);
		$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$error = curl_error($ch);
		curl_close($ch);

		if ($error) {
			throw new Exception("Embedder service request failed: {$error}");
		}

		if ($httpCode < 200 || $httpCode >= 300) {
			throw new Exception("Embedder service returned HTTP {$httpCode}: {$response}");
		}

		$data = json_decode($response, true);
		if ($data === null) {
			throw new Exception("Invalid JSON from embedder service: {$response}");
		}

		return $data;
	}

	/**
	 * Generate embeddings for a single file.
	 *
	 * @param string $fileId Nextcloud file ID
	 * @param string $filePath Server-side file path
	 * @return array {embedding: float[], status: string}
	 */
	public function embedFile(string $fileId, string $filePath): array {
		// Download file content to temp file for the embedder
		$tempFile = tmpfile();
		$tempMeta = stream_get_meta_data($tempFile);
		$tempPath = $tempMeta['uri'];

		try {
			// Read file content from Nextcloud filesystem
			$node = $this->getFileNode($fileId);
			$content = $node->getContent();
			file_put_contents($tempPath, $content);
			fseek($tempFile, 0);

			$result = $this->request('POST', '/api/v1/embed', [
				'file_id' => $fileId,
				'file_path' => $filePath,
			]);

			return $result;
		} finally {
			fclose($tempFile);
		}
	}

	/**
	 * Search for images matching a text query.
	 *
	 * @param string $query Search query text
	 * @param int $limit Maximum number of results
	 * @param float $threshold Minimum similarity score
	 * @return array List of matching files with scores
	 */
	public function search(string $query, int $limit = 20, float $threshold = 0.5): array {
		return $this->request('POST', '/api/v1/search', [
			'query' => $query,
			'limit' => $limit,
			'threshold' => $threshold,
		]);
	}

	/**
	 * Get embedding status for a file.
	 *
	 * @param string $fileId Nextcloud file ID
	 * @return array {status: string, progress: int}
	 */
	public function getStatus(string $fileId): array {
		return $this->request('GET', "/api/v1/status/{$fileId}");
	}

	/**
	 * Get all registered folders from the embedder service.
	 *
	 * @return array List of registered folder paths
	 */
	public function getFolders(): array {
		return $this->request('GET', '/api/v1/folders');
	}

	/**
	 * Register a folder for monitoring.
	 *
	 * @param string $folderPath Path to register
	 * @return array {status: string}
	 */
	public function registerFolder(string $folderPath): array {
		return $this->request('POST', '/api/v1/folders', [
			'path' => $folderPath,
		]);
	}

	/**
	 * Get thumbnail data for a file.
	 *
	 * @param string $fileId Nextcloud file ID
	 * @return array {thumbnail: string, format: string} Base64-encoded thumbnail
	 */
	public function getThumbnail(string $fileId): array {
		return $this->request('GET', "/api/v1/thumbnail/{$fileId}");
	}

	/**
	 * Get a Nextcloud file node by ID.
	 */
	private function getFileNode(string $fileId): \OCP\Files\File {
		$root = \OC::$server->getMountPointContainer(0);
		$nodes = $root->getById((int) $fileId);
		if (empty($nodes)) {
			throw new Exception("File not found: {$fileId}");
		}
		return $nodes[0];
	}
}
