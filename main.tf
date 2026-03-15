# main.tf — Automated Infrastructure for The Other Side
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  # Plugged in from your main.py config
  project = "the-other-side-489308" 
  region  = "us-central1"
}

# 1. Enable Required APIs (Matches your deploy.sh list)
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "texttospeech.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "vision.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com"
  ])
  service = each.key
  disable_on_destroy = false
}

# 2. GCS Bucket for Videos (Matches your BUCKET_NAME)
resource "google_storage_bucket" "video_bucket" {
  name          = "the-other-side-videos-489308"
  location      = "US-CENTRAL1"
  force_destroy = true

  # Allow public viewing of generated videos as per your gsutil command
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_iam_binding" "public_rule" {
  bucket = google_storage_bucket.video_bucket.name
  role   = "roles/storage.objectViewer"
  members = ["allUsers"]
}

# 3. Firestore Database
resource "google_firestore_database" "database" {
  name        = "(default)"
  location_id = "us-central1"
  type        = "FIRESTORE_NATIVE"
}

# 4. Service Account & IAM Roles
resource "google_service_account" "sa" {
  account_id   = "the-other-side-sa"
  display_name = "The Other Side Service Account"
}

resource "google_project_iam_member" "sa_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/texttospeech.client",
    "roles/storage.objectAdmin",
    "roles/datastore.user",
    "roles/cloudvision.admin"
  ])
  project = "the-other-side-489308"
  role    = each.key
  member  = "serviceAccount:${google_service_account.sa.email}"
}