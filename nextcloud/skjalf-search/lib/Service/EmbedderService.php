<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\SkjalfSearch\Service;

use OCP\IDBConnection;
use OCP\ILogger;

/**
 * High-level service coordinating embedding operations.
 *
 * This service encapsulates the business logic for:
 * - Checking if a file needs embedding
 * - Queuing files for embedding
 * - Retrieving embedding status
 * - Managing registered folders
 */
class EmbedderService {
	private IDBConnection $db;
	private ILogger $logger;
	private \OCA\SkjalfSearch\Controller\APIClient $apiClient;
	private \OCA\SkjalfSearch\Db\EmbeddingMapper $mapper;

	public function __construct(
		IDBConnection $db,
		ILogger $logger,
		\OCA\SkjalfSearch\Controller\APIClient $apiClient,
		\OCA\SkjalfSearch\Db\EmbeddingMapper $mapper,
	) {
		$this->db = $db;
		$this->logger = $logger;
		$this->apiClient = $apiClient;
		$this->mapper = $mapper;
	}

	/**
	 * Check if a file is already embedded.
	 *
	 * @param int $fileId Nextcloud file ID
	 * @return bool
	 */
	public function isEmbedded(int $fileId): bool {
		try {
			$record = $this->mapper->findByFileId($fileId);
			return $record->getStatus() === 'complete';
		} catch (\OCP\AppFramework\Db\DoesNotExistException) {
			return false;
		}
	}

	/**
	 * Get embedding status for a file.
	 *
	 * @param int $fileId Nextcloud file ID
	 * @return array{status: string, progress: int, chroma_id: ?string, error: ?string}
	 */
	public function getEmbeddingStatus(int $fileId): array {
		try {
			$record = $this->mapper->findByFileId($fileId);
			return [
				'status' => $record->getStatus(),
				'progress' => $record->getProgress(),
				'chroma_id' => $record->getChromaId(),
				'error' => $record->getError(),
			];
		} catch (\OCP\AppFramework\Db\DoesNotExistException) {
			return [
				'status' => 'unknown',
				'progress' => 0,
				'chroma_id' => null,
				'error' => null,
			];
		}
	}

	/**
	 * Queue a file for embedding.
	 *
	 * @param int $fileId Nextcloud file ID
	 * @param string $filePath Server-side file path
	 */
	public function queueForEmbedding(int $fileId, string $filePath): void {
		$this->mapper->saveStatus($fileId, 'pending', null, 0);

		$jobList = \OC::$server->getJobList();
		$job = new \OCA\SkjalfSearch\BackgroundJob\EmbedFileJob($jobList);
		$job->setFileId($fileId);
		$job->setFilePath($filePath);
		$jobList->add($job);

		$this->logger->debug("Skjalf: Queued file for embedding: file_id={fileId}", ['fileId' => $fileId]);
	}

	/**
	 * Get all registered folders.
	 *
	 * @return array{folders: string[], embedder_available: bool}
	 */
	public function getFolders(): array {
		try {
			$folders = $this->apiClient->getFolders();
			return [
				'folders' => $folders,
				'embedder_available' => true,
			];
		} catch (\Exception $e) {
			return [
				'folders' => [],
				'embedder_available' => false,
				'error' => $e->getMessage(),
			];
		}
	}

	/**
	 * Register a folder for monitoring.
	 *
	 * @param string $folderPath Path to register
	 * @return array{status: string, error?: string}
	 */
	public function registerFolder(string $folderPath): array {
		try {
			$result = $this->apiClient->registerFolder($folderPath);
			return ['status' => 'registered'];
		} catch (\Exception $e) {
			return [
				'status' => 'error',
				'error' => $e->getMessage(),
			];
		}
	}

	/**
	 * Bulk embed all images in a folder.
	 *
	 * @param string $folderId Nextcloud folder ID
	 * @return array{total: int, queued: int, errors: int}
	 */
	public function bulkEmbedFolder(string $folderId): array {
		$total = 0;
		$queued = 0;
		$errors = 0;

		try {
			$root = \OC\Files\Filesystem::getRoot();
			$folder = $root->getById((int) $folderId)[0] ?? null;

			if (!$folder instanceof \OCP\Files\Folder) {
				return ['total' => 0, 'queued' => 0, 'errors' => 1, 'error' => 'Folder not found'];
			}

			$this->processFolder($folder, $total, $queued, $errors);
		} catch (\Exception $e) {
			return ['total' => 0, 'queued' => 0, 'errors' => 1, 'error' => $e->getMessage()];
		}

		return ['total' => $total, 'queued' => $queued, 'errors' => $errors];
	}

	/**
	 * Recursively process a folder for embedding.
	 */
	private function processFolder(
		\OCP\Files\Node $node,
		int &$total,
		int &$queued,
		int &$errors,
	): void {
		if ($node instanceof \OCP\Files\File) {
			$total++;
			if (!str_starts_with($node->getMimeType(), 'image/')) {
				return;
			}

			$fileId = $node->getId();
			if ($this->isEmbedded($fileId)) {
				return; // Skip already embedded files
			}

			try {
				$this->queueForEmbedding($fileId, $node->getPath());
				$queued++;
			} catch (\Exception $e) {
				$errors++;
			}
		} elseif ($node instanceof \OCP\Files\Folder) {
			foreach ($node->getDirectoryListing() as $child) {
				$this->processFolder($child, $total, $queued, $errors);
			}
		}
	}

	/**
	 * Search for images matching a query.
	 *
	 * @param string $query Search query
	 * @param int $limit Max results
	 * @param float $threshold Min similarity
	 * @return array{results: array, count: int}
	 */
	public function search(string $query, int $limit = 20, float $threshold = 0.5): array {
		try {
			$results = $this->apiClient->search($query, $limit, $threshold);
			return [
				'results' => $results['results'] ?? [],
				'count' => count($results['results'] ?? []),
			];
		} catch (\Exception $e) {
			return [
				'results' => [],
				'count' => 0,
				'error' => $e->getMessage(),
			];
		}
	}
}
