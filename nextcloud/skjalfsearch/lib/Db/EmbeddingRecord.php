<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\Skjalfsearch\Db;

use OCP\AppFramework\Db\Entity;

/**
 * Entity representing embedding status for a file.
 *
 * @method int getFileId()
 * @method void setFileId(int $fileId)
 * @method string getStatus()
 * @method void setStatus(string $status)
 * @method string|null getChromaId()
 * @method void setChromaId(?string $chromaId)
 * @method int getProgress()
 * @method void setProgress(int $progress)
 * @method string|null getError()
 * @method void setError(?string $error)
 * @method string|null getFilePath()
 * @method void setFilePath(?string $filePath)
 */
class EmbeddingRecord extends Entity {
	public const TABLE = 'skjalf_embeddings';

	public function __construct() {
		$this->addType('file_id', 'integer');
		$this->addType('status', 'string');
		$this->addType('chroma_id', 'string');
		$this->addType('progress', 'integer');
		$this->addType('error', 'string');
		$this->addType('file_path', 'string');
		$this->addType('created_at', 'datetime');
		$this->addType('updated_at', 'datetime');
	}
}
