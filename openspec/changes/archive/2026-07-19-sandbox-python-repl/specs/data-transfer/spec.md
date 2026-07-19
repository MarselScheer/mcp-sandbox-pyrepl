## ADDED Requirements

### Requirement: Write file to data volume
The system SHALL write content to a file in the session's mounted `/data` directory, making it accessible inside the container.

- `session_id`: target session
- `path`: relative path within the `/data` directory (e.g., `"input/sales.csv"`)
- `content`: file content (string or bytes)

#### Scenario: Write a text file
- **WHEN** a client calls `write_file(session_id="sess_abc", path="input/data.csv", content="a,b,c\n1,2,3")`
- **THEN** the file `/data/input/data.csv` exists inside the container with the specified content

#### Scenario: Write binary file
- **WHEN** a client calls `write_file(session_id="sess_abc", path="image.png", content=<base64-encoded-bytes>)`
- **THEN** the file `/data/image.png` exists inside the container with the decoded binary content

#### Scenario: Overwrite existing file
- **WHEN** a client calls `write_file(session_id="sess_abc", path="data.csv", content="new content")`
- **AND** the file already exists
- **THEN** the file is overwritten with the new content

### Requirement: Read file from data volume
The system SHALL read a file from the session's mounted `/data` directory and return its content.

- `session_id`: target session
- `path`: relative path within the `/data` directory

#### Scenario: Read a text file
- **WHEN** a file `data.csv` exists in `/data/` inside the container
- **AND** a client calls `read_file(session_id="sess_abc", path="data.csv")`
- **THEN** the system returns the file content as a string

#### Scenario: Read a binary file
- **WHEN** a binary file `plot.png` exists in `/data/` inside the container
- **AND** a client calls `read_file(session_id="sess_abc", path="plot.png")`
- **THEN** the system returns the file content as base64-encoded bytes

#### Scenario: Read non-existent file
- **WHEN** a client calls `read_file(session_id="sess_abc", path="nonexistent.csv")`
- **THEN** the system returns an error indicating the file does not exist

### Requirement: List files in data volume
The system SHALL list files and directories in the session's `/data` directory.

- `session_id`: target session
- `path`: optional relative path to list (default: root of `/data`)

#### Scenario: List files in data root
- **WHEN** a client calls `list_files(session_id="sess_abc")`
- **THEN** the system returns a list of files and directories at the root of `/data`

#### Scenario: List files in subdirectory
- **WHEN** a client calls `list_files(session_id="sess_abc", path="output")`
- **THEN** the system returns a list of files in `/data/output/`