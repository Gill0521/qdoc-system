-- Q:DOC database

DROP DATABASE IF EXISTS qdoc;
CREATE DATABASE qdoc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE qdoc;

-- MySQL dump 10.13  Distrib 8.0.44, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: qdoc
-- ------------------------------------------------------
-- Server version	8.0.44

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `activity_logs`
--

DROP TABLE IF EXISTS `activity_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `activity_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `action` varchar(50) NOT NULL,
  `description` text NOT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=565 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `announcements`
--

DROP TABLE IF EXISTS `announcements`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `announcements` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(255) NOT NULL,
  `content` text NOT NULL,
  `status` enum('Published','Hidden') DEFAULT 'Published',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `document_settings`
--

DROP TABLE IF EXISTS `document_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `document_settings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `doc_name` varchar(100) NOT NULL,
  `price` decimal(10,2) NOT NULL DEFAULT '0.00',
  `requirements` text,
  `is_available` tinyint(1) DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `notifications`
--

DROP TABLE IF EXISTS `notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int unsigned NOT NULL,
  `request_id` int DEFAULT NULL,
  `title` varchar(50) NOT NULL,
  `message` text NOT NULL,
  `is_read` tinyint(1) DEFAULT '0',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=61 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `requests`
--

DROP TABLE IF EXISTS `requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `requests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int unsigned NOT NULL,
  `document_type` varchar(100) NOT NULL,
  `purpose` text,
  `status` enum('Pending','Approved','Processing','Ready for Pickup','Completed','Rejected') DEFAULT 'Pending',
  `request_date` datetime DEFAULT CURRENT_TIMESTAMP,
  `payment_method` varchar(50) NOT NULL DEFAULT 'Cash',
  `payment_reference` varchar(100) DEFAULT NULL,
  `pickup_date` date DEFAULT NULL,
  `payment_status` enum('Paid','Unpaid') DEFAULT 'Unpaid',
  `requirement_file` text,
  `official_notes` text,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `requests_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=44 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `system_settings`
--

DROP TABLE IF EXISTS `system_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `system_settings` (
  `id` int NOT NULL DEFAULT '1',
  `brgy_name` varchar(255) DEFAULT 'Barangay Sto. Niño',
  `city_name` varchar(255) DEFAULT 'Parañaque City',
  `province_name` varchar(255) DEFAULT 'Metro Manila',
  `email` varchar(255) DEFAULT NULL,
  `contact_number` varchar(50) DEFAULT NULL,
  `maintenance_mode` tinyint DEFAULT '0',
  `captain_name` varchar(255) DEFAULT 'Hon. Captain Name',
  `gcash_number` varchar(50) DEFAULT NULL,
  `gcash_qr` varchar(255) DEFAULT NULL,
  `logo_left` varchar(255) DEFAULT 'assets/images/city-logo.png',
  `logo_right` varchar(255) DEFAULT 'assets/images/brgy-logo.png',
  `allow_registration` tinyint DEFAULT '1',
  `maya_number` varchar(50) DEFAULT '',
  `maya_qr` varchar(255) DEFAULT '',
  `bank_name` varchar(100) DEFAULT '',
  `bank_account_num` varchar(100) DEFAULT '',
  `bank_account_name` varchar(100) DEFAULT '',
  `bank_qr` varchar(255) DEFAULT '',
  `official_code` varchar(50) DEFAULT 'BrgyOfficial2025',
  `admin_code` varchar(50) DEFAULT 'BrgyAdmin2025',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `role` enum('Resident','Official','Admin') NOT NULL,
  `fullname` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `birthdate` date NOT NULL,
  `sex` enum('Male','Female') NOT NULL,
  `civil_status` enum('Single','Married','Widowed','Separated') NOT NULL,
  `contact` varchar(11) NOT NULL,
  `address` varchar(255) NOT NULL,
  `password` varchar(255) NOT NULL,
  `id_front` varchar(255) NOT NULL,
  `id_back` varchar(255) NOT NULL,
  `profile_picture` varchar(255) NOT NULL,
  `account_status` enum('Pending','Approved','Rejected') NOT NULL DEFAULT 'Pending',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `verif_code` varchar(6) DEFAULT NULL,
  `verif_expiration` datetime DEFAULT NULL,
  `position` varchar(50) DEFAULT NULL,
  `remember_token` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  UNIQUE KEY `contact` (`contact`)
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-06-08 13:14:58


-- ---------------------------------------------------------------------
-- Default seed data for Q:DOC
-- ---------------------------------------------------------------------
USE qdoc;

INSERT INTO system_settings
(id, brgy_name, city_name, province_name, email, contact_number, maintenance_mode, captain_name,
 gcash_number, maya_number, bank_name, bank_account_num, bank_account_name,
 allow_registration, official_code, admin_code)
VALUES
(1, 'Barangay Sto. Niño', 'Parañaque City', 'Metro Manila', 'admin.gov@gmail.com', '09053063531', 0, 'Hon. Captain Name',
 '', '', '', '', '', 1, 'BrgyOfficial2025', 'BrgyAdmin2025')
ON DUPLICATE KEY UPDATE
 brgy_name=VALUES(brgy_name), city_name=VALUES(city_name), province_name=VALUES(province_name),
 email=VALUES(email), contact_number=VALUES(contact_number), maintenance_mode=VALUES(maintenance_mode),
 captain_name=VALUES(captain_name), allow_registration=VALUES(allow_registration),
 official_code=VALUES(official_code), admin_code=VALUES(admin_code);

DELETE FROM document_settings;
INSERT INTO document_settings (doc_name, price, requirements, is_available) VALUES
('Barangay Clearance', 50.00, 'Valid ID, Cedula', 1),
('Barangay ID', 100.00, '1x1 Picture, Valid ID', 1),
('Business Permit', 500.00, 'DTI Registration, Lease Contract', 1),
('Certificate of Indigency', 0.00, 'None', 1),
('Certificate of Residency', 50.00, 'Valid ID', 1),
('Solo Parent Application', 0.00, 'None', 1);

-- Default local admin account for first login.
-- Default local accounts for first login.
-- Admin:    admin@qdoc.local    / Admin12345!
-- Official: official@qdoc.local / Official12345!
-- Resident: resident@qdoc.local / Resident12345!

INSERT INTO users
(role, fullname, email, birthdate, sex, civil_status, contact, address, password,
 id_front, id_back, profile_picture, account_status, position)
VALUES
('Admin', 'Q-DOC Administrator', 'admin@qdoc.local', '1900-01-01', 'Male', 'Single', '09999999999', 'Barangay Hall',
 '$2b$12$B2408RpnWDjpe.s7ftG7ke4GpJl9ZQdg9GkG/eEiOoStmfxhm4GvO', '', '', '', 'Approved', 'System Administrator'),
('Official', 'Barangay Official', 'official@qdoc.local', '1900-01-01', 'Female', 'Single', '09999999998', 'Barangay Hall',
 '$2b$12$bOz8i6uVyNSh9kzLSWv.ou0Qf1r69.9vJ.7gS7C4sDli.OmAOcl2y', '', '', 'assets/images/official-girl-member.jpg', 'Approved', 'Barangay Official'),
('Resident', 'Sample Resident', 'resident@qdoc.local', '2000-01-01', 'Male', 'Single', '09999999997', 'Sample Address, Barangay Sto. Niño',
 '$2b$12$HC1ytT2.bs4z1qEt6uvADOKHH9WfoJUwBeMdOr67JTuRovP/1SYrK', 'assets/images/default-id.jpg', 'assets/images/default-id.jpg', 'assets/images/default-id.jpg', 'Approved', NULL)
ON DUPLICATE KEY UPDATE
 fullname=VALUES(fullname), role=VALUES(role), password=VALUES(password), account_status=VALUES(account_status), position=VALUES(position);

INSERT INTO announcements (title, content, status)
SELECT 'Welcome to Q:DOC', 'This is the barangay online document request portal.', 'Published'
WHERE NOT EXISTS (SELECT 1 FROM announcements WHERE title='Welcome to Q:DOC');

SELECT 'QDOC database reset and seed completed successfully.' AS message;
