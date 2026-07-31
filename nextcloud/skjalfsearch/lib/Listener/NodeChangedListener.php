<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\Skjalfsearch\Listener;

use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Files\Events\Node\NodeEvent;
use OCP\Files\File;
use OCP\Files\NodeRemovedEvent;
use OCP\Files\NodeTouchedEvent;
use OCP\ILogger;

/**
 * Listens for node-level events (create, update, delete).
 *
 * This complements FileChangedListener by catching events that may not
 * trigger the more specific listener.
 */
class NodeChangedListener implements IEventListener {
	private ILogger $logger;

	public function __construct(ILogger $logger) {
		$this->logger = $logger;
	}

	public function handle(Event $event): void {
		if (!$event instanceof NodeEvent) {
			return;
		}

		$node = $event->getNode();

		// Only handle files
		if (!$node instanceof File) {
			return;
		}

		// Only handle image files
		$mimeType = $node->getMimeType();
		if (!str_starts_with($mimeType, 'image/')) {
			return;
		}

		$fileId = $node->getId();

		// If this is a delete event, remove from embeddings
		if ($event instanceof NodeRemovedEvent) {
			$this->logger->info("Skjalf: File removed, removing embedding: file_id={fileId}", ['fileId' => $fileId]);
			$this->removeEmbedding($fileId);
			return;
		}

		// For create/update, the FileChangedListener will handle it
		// This listener is a fallback for events that don't trigger FileChangedListener
	}

	/**
	 * Remove embedding record for a deleted file.
	 */
	private function removeEmbedding(int $fileId): void {
		$mapper = new \OCA\Skjalfsearch\Db\EmbeddingMapper(
			\OC::$server->getDatabaseConnection()
		);

		try {
			$record = $mapper->findByFileId($fileId);
			$mapper->delete($record);
		} catch (\OCP\AppFramework\Db\DoesNotExistException) {
			// No record to delete
		}
	}
}
