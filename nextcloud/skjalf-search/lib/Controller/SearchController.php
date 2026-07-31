<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\SkjalfSearch\Controller;

use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\JSONResponse;
use OCP\AppFramework\Http\ContentSecurityPolicy;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\IRequest;
use OCP\IUserSession;
use OCP\AppFramework\Http\TemplateResponse;

/**
 * REST API controller for semantic search operations.
 *
 * Endpoints:
 *   GET  /                                          - Render main page
 *   GET  /api/v1/search?q=...&limit=20&threshold=0.5  - Semantic search
 *   POST /api/v1/embed/file/{fileId}                  - Embed single file
 *   POST /api/v1/embed/folder/{folderId}              - Embed all files in folder
 *   GET  /api/v1/status/{fileId}                      - Check embedding status
 *   GET  /api/v1/folders                              - List registered folders
 *   POST /api/v1/folders                              - Register a folder
 */
class SearchController extends Controller {
	private APIClient $apiClient;
	private IUserSession $userSession;

	public function __construct(
		string $appName,
		IRequest $request,
		APIClient $apiClient,
		IUserSession $userSession,
	) {
		parent::__construct($appName, $request);
		$this->apiClient = $apiClient;
		$this->userSession = $userSession;
	}

	/**
	 * Perform a semantic search.
	 *
	 * @param string $query Search query
	 * @param int $limit Max results
	 * @param float $threshold Min similarity
	 */
	#[\OCP\AppFramework\Http\HttpResponse::STATUS_OK]
	public function search(string $query, int $limit = 20, float $threshold = 0.5): JSONResponse {
		if ($query === '') {
			return new JSONResponse(['error' => 'Query is required'], Http::STATUS_BAD_REQUEST);
		}

		try {
			$results = $this->apiClient->search($query, $limit, $threshold);
			return new JSONResponse([
				'query' => $query,
				'results' => $results['results'] ?? [],
				'count' => count($results['results'] ?? []),
			]);
		} catch (\Exception $e) {
			return new JSONResponse([
				'error' => $e->getMessage(),
			], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * Embed a single file.
	 *
	 * @param string $fileId Nextcloud file ID
	 */
	public function embedFile(string $fileId): JSONResponse {
		try {
			// Resolve the file path from the current user's filesystem
			$user = $this->userSession->getUser();
			if ($user === null) {
				return new JSONResponse(['error' => 'Not authenticated'], Http::STATUS_UNAUTHORIZED);
			}

			$userFolder = $user->getUserFolder();
			$nodes = $userFolder->getById((int) $fileId);
			if (empty($nodes)) {
				return new JSONResponse(['error' => 'File not found'], Http::STATUS_NOT_FOUND);
			}

			$file = $nodes[0];
			if (!($file instanceof \OCP\Files\File)) {
				return new JSONResponse(['error' => 'Not a file'], Http::STATUS_BAD_REQUEST);
			}

			$filePath = $file->getPath();
			$result = $this->apiClient->embedFile((string) $fileId, $filePath);
			return new JSONResponse($result);
		} catch (\Exception $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * Embed all files in a folder.
	 *
	 * @param string $folderId Nextcloud folder ID
	 */
	public function embedFolder(string $folderId): JSONResponse {
		try {
			$user = $this->userSession->getUser();
			if ($user === null) {
				return new JSONResponse(['error' => 'Not authenticated'], Http::STATUS_UNAUTHORIZED);
			}

			$userFolder = $user->getUserFolder();
			$nodes = $userFolder->getById((int) $folderId);
			if (empty($nodes)) {
				return new JSONResponse(['error' => 'Folder not found'], Http::STATUS_NOT_FOUND);
			}

			$folder = $nodes[0];
			if (!($folder instanceof \OCP\Files\Folder)) {
				return new JSONResponse(['error' => 'Not a folder'], Http::STATUS_BAD_REQUEST);
			}

			$folderPath = $folder->getPath();
			$images = $this->collectImagesRecursive($folder);

			$results = [];
			foreach ($images as $image) {
				try {
					$result = $this->apiClient->embedFile($image['id'], $image['path']);
					$results[] = [
						'file_id' => $image['id'],
						'status' => $result['status'] ?? 'unknown',
					];
				} catch (\Exception $e) {
					$results[] = [
						'file_id' => $image['id'],
						'error' => $e->getMessage(),
					];
				}
			}

			return new JSONResponse([
				'folder_id' => $folderId,
				'folder_path' => $folderPath,
				'total' => count($images),
				'results' => $results,
			]);
		} catch (\Exception $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * Get embedding status for a file.
	 *
	 * @param string $fileId Nextcloud file ID
	 */
	public function status(string $fileId): JSONResponse {
		try {
			$status = $this->apiClient->getStatus($fileId);
			return new JSONResponse($status);
		} catch (\Exception $e) {
			return new JSONResponse([
				'status' => 'error',
				'error' => $e->getMessage(),
			], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * List registered folders.
	 */
	public function getFolders(): JSONResponse {
		try {
			$folders = $this->apiClient->getFolders();
			return new JSONResponse(['folders' => $folders]);
		} catch (\Exception $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * Register a folder for monitoring.
	 */
	public function registerFolder(): JSONResponse {
		$path = $this->request->getParam('path');
		if ($path === null || $path === '') {
			return new JSONResponse(['error' => 'Path is required'], Http::STATUS_BAD_REQUEST);
		}

		try {
			$result = $this->apiClient->registerFolder($path);
			return new JSONResponse($result);
		} catch (\Exception $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_SERVICE_UNAVAILABLE);
		}
	}

	/**
	 * Recursively collect all image files from a folder.
	 */
	private function collectImagesRecursive(\OCP\Files\Folder $folder): array {
		$images = [];
		$children = $folder->getDirectoryListing();
		foreach ($children as $node) {
			if ($node instanceof \OCP\Files\File) {
				$mime = $node->getMimeType();
				if (str_starts_with($mime, 'image/')) {
					$images[] = [
						'id' => $node->getId(),
						'name' => $node->getName(),
						'path' => $node->getPath(),
					];
				}
			} elseif ($node instanceof \OCP\Files\Folder) {
				$subImages = $this->collectImagesRecursive($node);
				$images = array_merge($images, $subImages);
			}
		}
		return $images;
	}

	/**
	 * Render the main search page.
	 *
	 * @return TemplateResponse
	 */
	#[NoAdminRequired]
	public function index(): TemplateResponse {
		$response = new TemplateResponse($this->appName, 'app', [], 'base');
		$csp = new ContentSecurityPolicy();
		$csp->addAllowedScriptDomain('\'self\'');
		$csp->addAllowedScriptDomain('\'unsafe-inline\'');
		$csp->addAllowedImgDomain('\'self\'');
		$csp->addAllowedStyleDomain('\'self\'');
		$csp->addAllowedStyleDomain('\'unsafe-inline\'');
		$response->setContentSecurityPolicy($csp);
		return $response;
	}
}
