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
use OCP\Files\File;
use OCP\Files\Node;
use OCP\Files\NodeRemovedEvent;
use OCP\Files\NodeTouchedEvent;
use OCP\ILogger;

/**
 * Listens for file change events and triggers embedding.
 *
 * When an image file is created or modified in a monitored folder,
 * this listener queues it for embedding via the background job system.
 */
class FileChangedListener implements IEventListener {
	private ILogger $logger;

	public function __construct(ILogger $logger) {
		$this->logger = $logger;
	}

	public function handle(Event $event): void {
		// Only handle NodeTouchedEvent and NodeRemovedEvent
		if (!$event instanceof NodeTouchedEvent && !$event instanceof NodeRemovedEvent) {
			return;
		}

		$node = $event->getNode();

		// Only process files, not directories
		if (!$node instanceof File) {
			return;
		}

		// Only process image files
		$mimeType = $node->getMimeType();
		if (!str_starts_with($mimeType, 'image/')) {
			return;
		}

		$fileId = $node->getId();
		$filePath = $node->getPath();

		$this->logger->debug(
			"Skjalf: Image file changed, queuing for embedding: file_id={fileId} path={path}",
			['fileId' => $fileId, 'path' => $filePath]
		);

		// Queue the file for embedding via the background job
		$this->queueForEmbedding($fileId, $filePath);
	}

	/**
	 * Add a file to the embedding queue.
	 *
	 * Uses Nextcloud's job queue to schedule embedding.
	 */
	private function queueForEmbedding(int $fileId, string $filePath): void {
		$job = new \OCA\Skjalfsearch\BackgroundJob\EmbedFileJob(
			\OC::$server->getJobList()
		);
		$job->setFileId($fileId);
		$job->setFilePath($filePath);
		\OC::$server->getJobList()->add($job);
	}
}
