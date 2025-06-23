package com.example.management.repositories;

import com.example.management.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);
    boolean existsByEmail(String email);
    List<User> findByRole(com.example.management.model.enums.Role role);

    @Query("SELECT u FROM User u WHERE u.role IN ('ADMIN', 'HR')")
    List<User> findAdminsAndHr();
    List<User> findByOfficeId(Long officeId);

    Optional<User> findByEmailAndTcNoAndPhoneNumber(String email, String tcNo, String phoneNumber);


    List<User> findAllByOfficeId(Long officeId);


}
