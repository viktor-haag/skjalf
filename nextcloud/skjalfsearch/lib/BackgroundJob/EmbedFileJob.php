<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\Skjalfsearch\BackgroundJob;

use OCP\BackgroundJob\QueuedJob;
use OCP\ILogger;

/**
 * Background job that processes file embedding requests.
 *
 * When a file is created or modified, FileChangedListener queues this job.
 * The job runs asynchronously, downloading the file and sending it to the
 * Python embedder service.
 */
class EmbedFileJob extends QueuedJob {
	private ILogger $logger;

	public function __construct() {
		parent::__construct();

		$this->logger = \OC::$server->getLogger();
	}

	/**
	 * Run the job.
	 *
	 * @param array $argument Job arguments containing file_id and file_path
	 */
	public function run($argument): void {
		$fileId = (int) ($argument['file_id'] ?? 0);
		$filePath = $argument['file_path'] ?? '';

		if ($fileId === 0 || $filePath === '') {
			$this->logger->error('Skjalf: Invalid job arguments', ['file_id' => $fileId, 'file_path' => $filePath]);
			return;
		}

		$this->logger->debug("Skjalf: Processing embed job for file_id={fileId}", ['fileId' => $fileId]);

		// Mark as processing
		$mapper = new \OCA\Skjalfsearch\Db\EmbeddingMapper(\OC::$server->getDatabaseConnection());
		$mapper->saveStatus($fileId, 'processing', null, 10);

		try {
			// Get the file content
			$node = $this->getFileNode($fileId);
			if ($node === null) {
				$mapper->saveStatus($fileId, 'error', null, 0, 'File not found');
				return;
			}

			$content = $node->getContent();
			if (strlen($content) === 0) {
				$mapper->saveStatus($fileId, 'error', null, 0, 'File is empty');
				return;
			}

			// Send to embedder service
			$client = new \OCA\Skjalfsearch\Controller\APIClient();
			$result = $client->embedFile((string) $fileId, $filePath);

			// Update status
			$chromaId = $result['chroma_id'] ?? null;
			$mapper->saveStatus($fileId, 'complete', $chromaId, 100);

			$this->logger->info("Skjalf: File embedded successfully: file_id={fileId} chroma_id={chromaId}", [
				'fileId' => $fileId,
				'chromaId' => $chromaId,
			]);
		} catch (\Exception $e) {
			$this->logger->error("Skjalf: Embed failed for file_id={fileId}: {error}", [
				'fileId' => $fileId,
				'error' => $e->getMessage(),
			]);

			$mapper->saveStatus($fileId, 'error', null, 0, $e->getMessage());
		}
	}

	/**
	 * Get a file node by ID.
	 */
	private function getFileNode(int $fileId): ?\OCP\Files\File {
		try {
			$root = \OC\Files\Filesystem::getRoot();
			$nodes = $root->getById($fileId);
			if (empty($nodes)) {
				return null;
			}
			$node = $nodes[0];
			if (!$node instanceof \OCP\Files\File) {
				return null;
			}
			return $node;
		} catch (\Exception $e) {
			$this->logger->error("Skjalf: Failed to get file node: {error}", ['error' => $e->getMessage()]);
			return null;
		}
	}
}
